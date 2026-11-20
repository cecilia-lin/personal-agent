"""Standalone bounded data job; use --max-products 6 for the first smoke run."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from app.preparation.job import PreparationJob, STAGES


@contextmanager
def exclusive_output(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = output / "job.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("This output is locked; inspect the prior job before resuming") from None
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=(*STAGES, "all"))
    parser.add_argument("--max-products", type=int, default=6)
    parser.add_argument("--enrich-products", type=int, default=6)
    parser.add_argument("--max-model-calls", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".local/cognee-job-smoke")
    parser.add_argument("--synthetic-owner", required=True)
    args = vars(parser.parse_args())
    stage = args.pop("stage")
    load_dotenv(ROOT / ".env")
    with exclusive_output(args["output"]):
        job = PreparationJob(**args)
        manifest = job.run(stage)
    if any(v["state"] in {"failed", "blocked", "pending"} for v in manifest["stages"].values()):
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error_class": type(exc).__name__, "message": "Preparation stopped; inspect the local manifest. No credentials printed."}))
        raise SystemExit(1)
