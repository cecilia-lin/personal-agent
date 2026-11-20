"""Shared Statsig Server Core and attached AI SDK, initialized per process."""
import logging
import os

from statsig_ai import StatsigAI, StatsigAttachConfig
from statsig_python_core import Statsig, StatsigOptions, StatsigUser

logger = logging.getLogger(__name__)
client: Statsig | None = None
ai_client: StatsigAI | None = None
initialization_verified = False
last_error: str | None = None


def initialize():
    global client, ai_client, initialization_verified, last_error
    if client is not None:
        return
    if os.getenv("INTEGRATIONS_ENABLED", "true").lower() == "false":
        return
    key = (os.getenv("STATSIG_SERVER_SECRET_KEY") or os.getenv("STATSIG_SERVER_SECRET", "")).strip()
    if not key:
        return
    try:
        options = StatsigOptions()
        options.environment = "development"
        options.init_timeout_ms = 5000
        client = Statsig(key, options)
        client.initialize().wait()
        details = client.get_initialize_details()
        initialization_verified = bool(details.init_success and details.is_config_spec_ready and details.failure_details is None)
        if not initialization_verified:
            last_error = "Statsig initialization failed; check the server key and network."
            return
        ai_client = StatsigAI(statsig_source=StatsigAttachConfig(statsig=client))
        ai_client.initialize()
        last_error = None
    except Exception as exc:
        last_error = f"Statsig initialization failed ({type(exc).__name__})."
        logger.warning(last_error)


def track_task_started(user_id: str):
    if client is None or not initialization_verified:
        return
    try:
        client.log_event(user=StatsigUser(user_id), event_name="task_started")
    except Exception as exc:
        logger.warning("Statsig event enqueue failed (%s).", type(exc).__name__)


def shutdown():
    global client, ai_client, initialization_verified
    try:
        if ai_client is not None:
            ai_client.shutdown()
    finally:
        if client is not None:
            client.shutdown().wait()
        client, ai_client, initialization_verified = None, None, False


def status():
    return {
        "name": "Statsig",
        "status": "healthy" if initialization_verified else "error" if last_error else "not_configured",
        "detail": last_error or (
            "Server Core initialized; task_started logging and AI SDK attachment enabled. "
            "The enable_reranker gate is evaluated once per task and its assignment is persisted."
            if initialization_verified else "Set STATSIG_SERVER_SECRET in .env and restart the API."
        ),
        # This proves config initialization only, not event ingestion or an experiment.
        "verified": initialization_verified,
    }

def choose_reranker(user_id: str):
    result = {"key": "enable_reranker", "enabled": False, "variant": "disabled",
              "source": "local_default", "reason": "Statsig unavailable; deterministic ordering.",
              "experiment_exposure": False}
    if client is None or not initialization_verified:
        return result
    try:
        gate = client.get_feature_gate(StatsigUser(user_id), "enable_reranker")
        return {**result, "enabled": bool(gate.value), "variant": "enabled" if gate.value else "disabled",
                "source": "statsig", "rule_id": gate.rule_id,
                "reason": "Persisted Statsig gate; SDK owns exposure logging." if gate.rule_id else "Gate has no matching rule; default false. Confirm enable_reranker exists in Statsig."}
    except Exception as exc:
        return {**result, "reason": f"Statsig evaluation failed ({type(exc).__name__}); default false."}
