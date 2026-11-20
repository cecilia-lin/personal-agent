"""One Amplitude Analytics client for the API process."""
import logging
import os

from amplitude import Amplitude, BaseEvent
from amplitude_ai import AmplitudeAI, AIConfig
from datetime import datetime

logger = logging.getLogger(__name__)
client: Amplitude | None = None
ai_client: AmplitudeAI | None = None
last_delivery_code: int | None = None


def _delivered(event, code, message):
    global last_delivery_code
    last_delivery_code = code
    # Provider messages can contain payloads; retain only the status code.
    logger.info("Amplitude delivery event=%s code=%s", event.event_type, code)


def initialize():
    global client, ai_client
    if client is not None:
        return
    if os.getenv("INTEGRATIONS_ENABLED", "true").lower() == "false":
        return
    key = os.getenv("AMPLITUDE_API_KEY", "").strip()
    if not key:
        logger.warning("AMPLITUDE_API_KEY is not set; Amplitude events are disabled.")
        return
    client = Amplitude(key)
    client.configuration.server_zone = os.getenv("AMPLITUDE_SERVER_ZONE", "US")
    client.configuration.callback = _delivered
    ai_client = AmplitudeAI(amplitude=client, config=AIConfig(content_mode="metadata_only", redact_pii=True))


def track_task_started(user_id: str):
    if client is None:
        return
    try:
        client.track(BaseEvent(event_type="task_started", user_id=user_id))
    except Exception as exc:
        # Analytics must not turn a committed task into a failed request.
        logger.warning("Amplitude enqueue failed (%s).", type(exc).__name__)


def shutdown():
    global client, ai_client
    if client is not None:
        client.shutdown()
        client, ai_client = None, None


def status():
    detail = "Metadata-only product events and measured tool calls use Amplitude Analytics + AI SDK."
    if last_delivery_code is not None:
        detail += f" Last SDK delivery status: {last_delivery_code}; HTTP delivery only; dashboard visibility has not been verified."
    return {
        "name": "Amplitude", "status": "configured" if client else "not_configured",
        "detail": detail if client else "Set AMPLITUDE_API_KEY in .env and restart the API.",
        "verified": last_delivery_code == 200,
        "dashboard_verified": False,
    }

def track_metadata(user_id, metric):
    """Called only after SQL commit. Never export sources, money, goals, or document text."""
    if client is None:
        return
    properties = {k: metric.get(k) for k in (
        "session_id", "task_id", "run_id", "provenance", "latency_ms", "routing", "kind")}
    try:
        client.track(BaseEvent(event_type=metric["kind"], user_id=user_id,
            insert_id=metric["id"], time=int(datetime.fromisoformat(metric["timestamp"]).timestamp()*1000),
            event_properties=properties))
        if ai_client is not None and metric.get("latency_ms") is not None and metric.get("session_id"):
            ai_client.track_tool_call(user_id=user_id, agent_id="intent", tool_name=metric["kind"],
                latency_ms=metric["latency_ms"], success=metric["kind"] not in {"task_failed","execution_blocked"},
                session_id=metric["session_id"], trace_id=metric.get("run_id"), invocation_id=metric["id"],
                event_properties={"task_id": metric.get("task_id"), "run_id": metric.get("run_id"),
                                  "provenance": metric.get("provenance"), "routing": metric.get("routing")})
        if ai_client is not None and metric["kind"] in {"task_completed","task_failed"} and metric.get("session_id"):
            ai_client.track_session_end(user_id=user_id, agent_id="intent", session_id=metric["session_id"])
    except Exception as exc:
        logger.warning("Amplitude metadata enqueue failed (%s).", type(exc).__name__)
