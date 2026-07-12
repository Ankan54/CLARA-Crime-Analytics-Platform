"""Assert-style end-to-end smoke check against a running backend + deployed job function.

Flow: upload (raw/) -> process (Phase A: extract+checkpoint -> REVIEW_PENDING) ->
proceed (Phase B: load+archive -> COMPLETED) -> verify SQL rows.

For a check that doesn't need the backend server or Catalyst Job Scheduling running,
see catalyst_functions/ingest_processor/self_check.py (calls IngestProcessor directly).

Run: python backend/scripts/smoke_e2e.py
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _build_pg_conninfo() -> str:
    if _env("DATABASE_URL"):
        return _env("DATABASE_URL").replace("+psycopg", "")
    host = _env("DB_HOST")
    port = _env("DB_PORT", "5432")
    user = _env("DB_USER")
    password = _env("DB_PASSWORD").strip("\"'")
    name = _env("DB_NAME", "ksp_crime")
    ssl = _env("DB_SSL", "require")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}?sslmode={ssl}"


def _upload(base_url: str, file_path: Path, file_type: str, case_id: int | None = None) -> dict:
    files = [("files", (file_path.name, file_path.read_bytes(), "text/plain"))]
    data = {"file_types": file_type}
    if case_id is not None:
        data["case_id"] = str(case_id)
    response = requests.post(f"{base_url}/api/v1/upload", files=files, data=data, timeout=60)
    response.raise_for_status()
    payload = response.json()
    assert payload["files"][0]["status"] == "STORED", f"Upload did not store the file: {payload}"
    return payload


def _wait_for_status(base_url: str, run_id: str, targets: set[str], timeout_seconds: int = 600) -> dict:
    start = time.time()
    while time.time() - start < timeout_seconds:
        response = requests.get(f"{base_url}/api/v1/pipeline-status/{run_id}", timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") in targets or payload.get("status") == "FAILED":
            return payload
        time.sleep(2)
    raise TimeoutError(f"Run {run_id} did not reach {targets} within {timeout_seconds}s")


def main() -> int:
    base_url = _env("BACKEND_BASE_URL", "http://127.0.0.1:9000")
    fir_file = ROOT / "sample_data" / "live_demo" / "live_scn1" / "fir.txt"
    assert fir_file.exists(), f"Missing file: {fir_file}"

    print("[smoke] Uploading FIR for a new case...")
    upload_payload = _upload(base_url, fir_file, "fir", case_id=None)
    batch_id = upload_payload["batch_id"]

    print(f"[smoke] Triggering Phase A for batch {batch_id}...")
    process_response = requests.post(f"{base_url}/api/v1/process/{batch_id}", timeout=30)
    process_response.raise_for_status()
    process_payload = process_response.json()
    run_id = process_payload["run_id"]
    case_id = process_payload["case_id"]
    assert process_payload["status"] == "QUEUED", process_payload

    print(f"[smoke] Waiting for run {run_id} to reach REVIEW_PENDING...")
    status_a = _wait_for_status(base_url, run_id, {"REVIEW_PENDING"})
    assert status_a["status"] == "REVIEW_PENDING", status_a
    assert status_a["phase"] == "REVIEW", status_a
    assert status_a.get("checkpoint_prefix"), "Missing checkpoint_prefix after Phase A"

    print(f"[smoke] Proceeding to Phase B for run {run_id}...")
    proceed_response = requests.post(f"{base_url}/api/v1/process/{run_id}/proceed", timeout=30)
    proceed_response.raise_for_status()
    proceed_payload = proceed_response.json()
    assert proceed_payload["status"] == "QUEUED", proceed_payload

    print(f"[smoke] Waiting for run {run_id} to reach COMPLETED...")
    status_b = _wait_for_status(base_url, run_id, {"COMPLETED", "COMPLETED_WITH_REVIEW_PENDING"})
    assert status_b["status"] in {"COMPLETED", "COMPLETED_WITH_REVIEW_PENDING"}, status_b
    assert status_b["phase"] == "DONE", status_b

    print("[smoke] Validating persisted rows in PostgreSQL...")
    with psycopg.connect(_build_pg_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM CaseMaster WHERE CaseMasterID = %s", (int(case_id),))
            assert cur.fetchone(), "Expected a CaseMaster row for the new case"

            cur.execute("SELECT COUNT(*) AS c FROM EntityMap")
            entity_count = int(cur.fetchone()["c"])
            assert entity_count >= 1, "Expected EntityMap rows"

    print(f"\n[smoke] PASS: upload -> process -> proceed -> {status_b['status']} verified (case_id={case_id}, run_id={run_id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
