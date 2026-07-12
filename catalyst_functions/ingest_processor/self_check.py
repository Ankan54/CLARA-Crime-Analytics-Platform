"""Runnable self-check for the raw/processed/archive two-phase pipeline.

Runs Phase A directly against sample_data/live_demo/live_scn1/fir.txt, asserts the
processed/{case_id}/{run_id}/manifest.json checkpoint exists and status flips to
REVIEW_PENDING, then runs Phase B and asserts archive/ objects + SQL rows exist and
status flips to COMPLETED.

Talks to the real Postgres/Stratus/Neo4j/Pinecone from .env (same as a deployed
job run), but calls IngestProcessor directly in-process — no backend HTTP server
or Catalyst Job Scheduling required.

Run: python catalyst_functions/ingest_processor/self_check.py
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from catalyst_functions.ingest_processor.pipeline.processor import (  # noqa: E402
    IngestProcessor,
    RunParams,
    _build_database_url,
    _stratus_bucket,
)

FIR_FILE = ROOT / "sample_data" / "live_demo" / "live_scn1" / "fir.txt"


def _mint_run_id(case_id: int) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{case_id}_{ts}"


def main() -> int:
    assert FIR_FILE.exists(), f"Missing sample file: {FIR_FILE}"

    conn = psycopg.connect(_build_database_url(), row_factory=dict_row, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(CaseMasterID), 0) + 1 AS next_id FROM CaseMaster")
            case_id = int(cur.fetchone()["next_id"])
        run_id = _mint_run_id(case_id)
        batch_id = str(uuid.uuid4())
        print(f"[self_check] case_id={case_id} run_id={run_id} batch_id={batch_id}")

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO BatchUpload (batch_id, case_id, uploaded_by, created_at) VALUES (%s, %s, 'self_check', NOW())",
                (batch_id, None),
            )
            cur.execute(
                """
                INSERT INTO PipelineRun (run_id, batch_id, case_id, phase, checkpoint_prefix, status, current_stage, created_at, updated_at)
                VALUES (%s, %s, %s, 'EXTRACT', %s, 'QUEUED', 'QUEUED', NOW(), NOW())
                """,
                (run_id, batch_id, case_id, f"processed/{case_id}/{run_id}/"),
            )

        raw_key = f"raw/{batch_id}/fir_fir.txt"
        bucket = _stratus_bucket()
        bucket.put_object(raw_key, FIR_FILE.read_bytes(), options={"overwrite": "true"})
        print(f"[self_check] uploaded {raw_key}")

        # --- Phase A ---
        processor_a = IngestProcessor(RunParams(batch_id=batch_id, case_id=case_id, run_id=run_id, phase="extract"))
        try:
            result_a = processor_a.run_phase_a()
        finally:
            processor_a.close()
        print(f"[self_check] Phase A result: {result_a}")
        assert result_a["status"] == "REVIEW_PENDING", f"Expected REVIEW_PENDING, got {result_a}"

        manifest_bytes = bucket.get_object(f"processed/{case_id}/{run_id}/manifest.json")
        manifest_raw = manifest_bytes if isinstance(manifest_bytes, bytes) else manifest_bytes.read()
        assert manifest_raw, "manifest.json checkpoint is empty"
        print(f"[self_check] PASS: processed/{case_id}/{run_id}/manifest.json exists ({len(manifest_raw)} bytes)")

        with conn.cursor() as cur:
            cur.execute("SELECT status, phase FROM PipelineRun WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
        assert row["status"] == "REVIEW_PENDING" and row["phase"] == "REVIEW", f"Unexpected PipelineRun row after Phase A: {row}"
        print("[self_check] PASS: PipelineRun row is REVIEW_PENDING/REVIEW")

        # --- Phase B ---
        processor_b = IngestProcessor(RunParams(batch_id=batch_id, case_id=case_id, run_id=run_id, phase="load"))
        try:
            result_b = processor_b.run_phase_b()
        finally:
            processor_b.close()
        print(f"[self_check] Phase B result: {result_b}")
        assert result_b["status"] == "COMPLETED", f"Expected COMPLETED, got {result_b}"
        assert result_b["archived_files"] >= 1, f"Expected >=1 archived file, got {result_b}"

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM CaseMaster WHERE CaseMasterID = %s", (case_id,))
            assert cur.fetchone(), "CaseMaster row was not written by Phase B"
            cur.execute("SELECT COUNT(*) AS c FROM EntityMap WHERE sql_table IN ('CaseMaster', 'Accused', 'Victim', 'ComplainantDetails')")
            assert int(cur.fetchone()["c"]) >= 1, "Expected at least one EntityMap row"
        print("[self_check] PASS: CaseMaster + EntityMap rows written")

        archive_prefix = f"archive/{case_id}/{run_id}/"
        page = bucket.list_paged_objects(prefix=archive_prefix)
        archived_keys = [obj.to_dict().get("key") if hasattr(obj, "to_dict") else obj.get("key") for obj in page["contents"]]
        assert archived_keys, f"Expected archived object(s) under {archive_prefix}"
        print(f"[self_check] PASS: {archive_prefix} has {len(archived_keys)} object(s): {archived_keys}")

        raw_page = bucket.list_paged_objects(prefix=f"raw/{batch_id}/")
        assert not raw_page["contents"], f"raw/{batch_id}/ should be empty after archiving, found {raw_page['contents']}"
        print(f"[self_check] PASS: raw/{batch_id}/ is empty (archived)")

        with conn.cursor() as cur:
            cur.execute("SELECT status, phase FROM PipelineRun WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
        assert row["status"] == "COMPLETED" and row["phase"] == "DONE", f"Unexpected PipelineRun row after Phase B: {row}"
        print("[self_check] PASS: PipelineRun row is COMPLETED/DONE")

        print(f"\n[self_check] ALL PASS (case_id={case_id}, run_id={run_id})")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
