"""Connectivity check for the Catalyst Signals pipeline-status transport.

Two independent checks, each asserting a 2xx:
  1. Publish  - POST a sample stage_update payload to SIGNALS_PIPELINE_PUBLISHER_URL
               (same shape processor.py._publish_signal sends). Confirms the
               Custom Publisher REST URL + credentials are wired correctly.
  2. Webhook  - POST a Signals-envelope-shaped payload (the confirmed live sample,
               with our fields at events[].data) straight to the backend's
               /internal/pipeline-event, and assert it unwraps + broadcasts it
               (delivered == 1). This exercises the webhook side even before the
               Signals Rule/Webhook target exists in the console (see plan step 4).

Run: python scripts/test_signals.py [--url PUBLISHER_URL] [--backend-url BASE_URL]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def test_publish(publisher_url: str, run_id: str) -> None:
    if not publisher_url:
        print("SKIP  Publish: SIGNALS_PIPELINE_PUBLISHER_URL not set (pass --url to override).")
        return
    payload = {
        "run_id": run_id,
        "stage": "TEST_SIGNAL",
        "status": "in_progress",
        "file": None,
        "files_progress": {},
        "ts": _utc_now(),
    }
    response = requests.post(publisher_url, json=payload, timeout=10)
    response.raise_for_status()
    print(f"PASS  Publish -> {publisher_url}: {response.status_code}")


def test_webhook_unwrap(backend_url: str, secret: str, run_id: str) -> None:
    envelope = {
        "rule_id": "test-rule",
        "target_id": "test-target",
        "version": 1,
        "attempt": 1,
        "account": {"org_id": "test-org", "project": {"environment": "Development", "name": "ksp-datathon", "id": "test-project"}},
        "events": [
            {
                "data": {
                    "run_id": run_id,
                    "file": "test_file.pdf",
                    "stage": "TEST_SIGNAL",
                    "status": "in_progress",
                    "ts": _utc_now(),
                },
                "id": str(uuid.uuid4()),
                "time_in_ms": str(int(datetime.now(tz=timezone.utc).timestamp() * 1000)),
                "source": "publisher_id:test/service:custom",
                "event_config": {"api_name": "stage_update", "id": "test-event-config"},
            }
        ],
    }
    url = backend_url.rstrip("/") + "/internal/pipeline-event"
    response = requests.post(url, json=envelope, headers={"X-Splink-Secret": secret}, timeout=10)
    response.raise_for_status()
    body = response.json()
    if body.get("delivered") != 1:
        raise RuntimeError(f"Expected delivered=1, got {body}")
    print(f"PASS  Webhook unwrap -> {url}: {body}")

    # A second delivery of the same event id must be deduped, not double-broadcast.
    response2 = requests.post(url, json=envelope, headers={"X-Splink-Secret": secret}, timeout=10)
    response2.raise_for_status()
    body2 = response2.json()
    if body2.get("delivered") != 0:
        raise RuntimeError(f"Expected duplicate event id to be deduped (delivered=0), got {body2}")
    print(f"PASS  Webhook dedupe on repeat event id: {body2}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SIGNALS_PIPELINE_PUBLISHER_URL", ""), help="Publisher REST URL override.")
    parser.add_argument("--backend-url", default=os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:9000"), help="Backend base URL.")
    parser.add_argument("--secret", default=os.getenv("SPLINK_SHARED_SECRET", "change-me"), help="Inbound webhook secret.")
    args = parser.parse_args()

    run_id = f"signals-test_{int(datetime.now(tz=timezone.utc).timestamp())}"
    failures = 0
    for name, fn in [
        ("publish", lambda: test_publish(args.url, run_id)),
        ("webhook", lambda: test_webhook_unwrap(args.backend_url, args.secret, run_id)),
    ]:
        try:
            fn()
        except Exception as exc:
            failures += 1
            print(f"FAIL  {name}: {exc}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
