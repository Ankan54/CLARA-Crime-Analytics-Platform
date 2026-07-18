"""
Trigger a test Phase A run against the Catalyst ingest_processor function.

Steps:
1. Connect to DB, mint case_id / batch_id / run_id
2. Insert BatchUpload + PipelineRun rows
3. Upload a sample FIR from sample_data/ to Stratus under raw/{batch_id}/
4. Submit the job via REST to the Catalyst Job Scheduling API
5. Print the job submission response

Run: python scripts/trigger_test.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

import psycopg
import requests
from psycopg.rows import dict_row


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
DB_HOST = os.environ["DB_HOST"]
DB_PORT = os.environ["DB_PORT"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ["DB_NAME"]
DB_SSL = os.environ["DB_SSL"]

ZOHO_AUTH_DOMAIN = os.environ.get("ZOHO_CATALYST_AUTH_DOMAIN", "https://accounts.zohoportal.in")
ZOHO_PROJECT_DOMAIN = os.environ.get("ZOHO_CATALYST_PROJECT_DOMAIN", "https://api.catalyst.zoho.in")
ZOHO_PROJECT_ID = os.environ["ZOHO_CATALYST_PROJECT_ID"]
ZOHO_CLIENT_ID = os.environ["ZOHO_CATALYST_CLIENT_ID"]
ZOHO_CLIENT_SECRET = os.environ["ZOHO_CATALYST_CLIENT_SECRET"]
ZOHO_REFRESH_TOKEN = os.environ["ZOHO_CATALYST_REFRESH_TOKEN"]
ZOHO_STRATUS_BUCKET = os.environ.get("ZOHO_STRATUS_BUCKET", "ksp-data-files")

# From the portal screenshot
JOBPOOL_ID = "42220000000026052"
FUNCTION_ID = "42220000000026012"
JOBPOOL_NAME = "ingestpool"
FUNCTION_NAME = "ingest_processor"

SAMPLE_FIR = ROOT / "sample_data" / "live_demo" / "live_scn1" / "fir.txt"
if not SAMPLE_FIR.exists():
    # fallback: any .txt in live_demo
    candidates = list((ROOT / "sample_data" / "live_demo").rglob("*.txt"))
    if not candidates:
        sys.exit("No sample .txt file found in sample_data/live_demo/")
    SAMPLE_FIR = candidates[0]

print(f"[trigger_test] Using sample file: {SAMPLE_FIR.relative_to(ROOT)}")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _db_url() -> str:
    pw = DB_PASSWORD.strip("\"'")
    return f"postgresql://{DB_USER}:{pw}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode={DB_SSL}"


def _get_access_token() -> str:
    r = requests.post(
        f"{ZOHO_AUTH_DOMAIN}/oauth/v2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": ZOHO_CLIENT_ID,
            "client_secret": ZOHO_CLIENT_SECRET,
            "refresh_token": ZOHO_REFRESH_TOKEN,
        },
        timeout=20,
    )
    r.raise_for_status()
    payload = r.json()
    token = payload.get("access_token")
    if not token:
        sys.exit(f"[trigger_test] Token refresh failed: {payload}")
    print(f"[trigger_test] Token OK  scope={payload.get('scope', '<none>')}")
    return str(token)


def _patch_zcatalyst():
    try:
        from zcatalyst_sdk._http_client import HttpClient
        if getattr(HttpClient.request, "_ksp_patched", False):
            return
        original = HttpClient.request
        def _request(self, method, url=None, path=None, *args, **kwargs):
            if url is None and path and str(path).startswith("/oauth"):
                path = path.lstrip("/")
            return original(self, method, url, path, *args, **kwargs)
        _request._ksp_patched = True
        HttpClient.request = _request
    except Exception:
        pass


def _stratus_upload(key: str, data: bytes, token: str) -> None:
    # Use zcatalyst_sdk for Stratus upload (signature-based)
    os.environ.setdefault("X_ZOHO_CATALYST_ACCOUNTS_URL", ZOHO_AUTH_DOMAIN)
    os.environ.setdefault("X_ZOHO_CATALYST_CONSOLE_URL", ZOHO_PROJECT_DOMAIN)
    os.environ.setdefault("X_ZOHO_STRATUS_RESOURCE_SUFFIX", ".zohostratus.in")
    _patch_zcatalyst()

    from zcatalyst_sdk import credentials, types
    import zcatalyst_sdk

    cred = credentials.RefreshTokenCredential({
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
    })
    opts = types.ICatalystOptions(
        project_id=ZOHO_PROJECT_ID,
        project_key=os.environ.get("ZOHO_CATALYST_PROJECT_KEY", ""),
        environment=os.environ.get("ZOHO_CATALYST_ENVIRONMENT", "Development"),
        project_domain=ZOHO_PROJECT_DOMAIN,
    )
    try:
        app = zcatalyst_sdk.get_app()
    except Exception:
        app = zcatalyst_sdk.initialize_app(credential=cred, options=opts)

    bucket = app.stratus().bucket(ZOHO_STRATUS_BUCKET)
    bucket.put_object(key, data, options={"overwrite": "true"})
    print(f"[trigger_test] Uploaded {key}  ({len(data)} bytes)")


def _submit_job(token: str, run_id: str, batch_id: str, case_id: int) -> dict:
    url = f"{ZOHO_PROJECT_DOMAIN}/baas/v1/project/{ZOHO_PROJECT_ID}/job_scheduling/job"
    payload = {
        "job_name": f"test_{run_id}"[:20],  # Catalyst: alphanumeric + underscore, 1-20 chars
        "jobpool_id": JOBPOOL_ID,
        "jobpool_name": JOBPOOL_NAME,
        "target_type": "Function",
        "target_name": FUNCTION_NAME,
        "target_id": FUNCTION_ID,
        "source_type": "API",
        "params": {
            "run_id": run_id,
            "batch_id": batch_id,
            "case_id": str(case_id),
            "phase": "extract",
        },
        "job_config": {"number_of_retries": 0, "retry_interval": 300},
    }
    print(f"[trigger_test] Submitting job to {url}")
    print(f"[trigger_test] Payload: {json.dumps(payload, indent=2)}")
    r = requests.post(
        url,
        headers={"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    print(f"[trigger_test] HTTP {r.status_code}")
    print(f"[trigger_test] Response: {r.text[:1000]}")
    if r.status_code not in (200, 201):
        sys.exit(f"[trigger_test] Job submit failed with {r.status_code}")
    return r.json()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    token = _get_access_token()

    # 1. Mint IDs
    conn = psycopg.connect(_db_url(), row_factory=dict_row, prepare_threshold=0)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(CaseMasterID), 0) + 1 AS next_id FROM CaseMaster")
            case_id = int(cur.fetchone()["next_id"])

        batch_id = str(uuid.uuid4())
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{case_id}_{ts}"
        checkpoint_prefix = f"processed/{case_id}/{run_id}/"
        print(f"[trigger_test] case_id={case_id}  batch_id={batch_id}  run_id={run_id}")

        # 2. Insert DB rows
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO BatchUpload (batch_id, case_id, uploaded_by, created_at) VALUES (%s, %s, 'test-trigger', NOW())",
                (batch_id, None),
            )
            cur.execute(
                """
                INSERT INTO PipelineRun (run_id, batch_id, case_id, phase, checkpoint_prefix, files_progress, current_stage, status, created_at, updated_at)
                VALUES (%s, %s, %s, 'EXTRACT', %s, '{}'::jsonb, 'QUEUED', 'QUEUED', NOW(), NOW())
                """,
                # case_id is NULL here — the FIR ingest will create the CaseMaster row
                # and update PipelineRun.case_id once the job runs
                (run_id, batch_id, None, checkpoint_prefix),
            )
        conn.commit()
        print("[trigger_test] DB rows inserted")
    finally:
        conn.close()

    # 3. Upload sample file to Stratus
    raw_key = f"raw/{batch_id}/fir_fir.txt"
    _stratus_upload(raw_key, SAMPLE_FIR.read_bytes(), token)

    # 4. Submit the job
    result = _submit_job(token, run_id, batch_id, case_id)
    job_id = (result.get("data") or result).get("job_id") or (result.get("data") or result).get("id")
    print(f"\n[trigger_test] Job submitted  job_id={job_id}  run_id={run_id}")
    print(f"[trigger_test] Check logs at: Catalyst Portal → Functions → {FUNCTION_NAME} → Logs")
    print(f"[trigger_test] Watch run:     SELECT * FROM PipelineRun WHERE run_id = '{run_id}'")


if __name__ == "__main__":
    main()
