from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import ProcessBatchResponse, ProcessProceedResponse
from ..services.catalyst_queue import build_processed_prefix, get_checkpoint_manifest, list_raw_objects, submit_ingestion_job
from ..services.findings import build_findings
from ..services.stage_labels import annotate_run, status_label


logger = logging.getLogger(__name__)
router = APIRouter(tags=["process"])

_NON_TERMINAL_STATUSES = {"QUEUED", "RUNNING", "REVIEW_PENDING"}


def _mint_run_id(case_id: int) -> str:
    """UUID-backed run ID for collision safety."""
    short_uuid = uuid.uuid4().hex[:8]
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{case_id}_{ts}_{short_uuid}"


@router.get("/runs")
def list_runs(
    case_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Newest-first PipelineRun listing — the FE's source for 'runs awaiting your
    review' (status=REVIEW_PENDING) and for rediscovering runs after a refresh."""
    limit = max(1, min(limit, 200))
    sql = """
        SELECT run_id, batch_id, case_id, phase, current_stage, status, error_message, created_at, updated_at
        FROM PipelineRun
        WHERE (:case_id IS NULL OR case_id = :case_id)
          AND (:status IS NULL OR status = :status)
        ORDER BY created_at DESC
        LIMIT :limit
    """
    rows = db.execute(text(sql), {"case_id": case_id, "status": status, "limit": limit}).mappings().all()
    return {"count": len(rows), "runs": [annotate_run(dict(r)) for r in rows]}


@router.post("/process/{batch_id}", response_model=ProcessBatchResponse)
def process_batch(batch_id: str, db: Session = Depends(get_db)) -> ProcessBatchResponse:
    batch = db.execute(
        text("SELECT batch_id, case_id, scenario_key, scenario_generation FROM BatchUpload WHERE batch_id = :batch_id"),
        {"batch_id": batch_id},
    ).mappings().first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")

    if not list_raw_objects(batch_id):
        raise HTTPException(status_code=400, detail="No raw files found for this batch.")

    existing_run = db.execute(
        text(
            "SELECT run_id, status FROM PipelineRun WHERE batch_id = :batch_id AND status = ANY(:statuses) "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"batch_id": batch_id, "statuses": list(_NON_TERMINAL_STATUSES)},
    ).mappings().first()
    if existing_run is not None:
        raise HTTPException(
            status_code=409,
            detail=f"This batch is already being processed (run {existing_run['run_id']}, status={existing_run['status']}).",
        )

    case_id = batch["case_id"]
    scenario_key = batch["scenario_key"]
    scenario_generation = batch["scenario_generation"]

    if case_id is None:
        next_id = db.execute(text("SELECT COALESCE(MAX(CaseMasterID), 0) + 1 AS next_id FROM CaseMaster")).mappings().one()
        case_id = int(next_id["next_id"])

    run_id = _mint_run_id(case_id)
    checkpoint_prefix = build_processed_prefix(case_id, run_id)
    logger.info("process_batch batch_id=%s case_id=%s run_id=%s scenario=%s", batch_id, case_id, run_id, scenario_key)

    db.execute(
        text(
            """
            INSERT INTO PipelineRun
                (run_id, batch_id, case_id, phase, checkpoint_prefix, files_progress, current_stage, status,
                 scenario_key, scenario_generation, created_at, updated_at)
            VALUES
                (:run_id, :batch_id, :case_id, 'EXTRACT', :checkpoint_prefix, '{}'::jsonb, 'QUEUED', 'QUEUED',
                 :scenario_key, :scenario_generation, NOW(), NOW())
            """
        ),
        {
            "run_id": run_id,
            "batch_id": batch_id,
            "case_id": case_id,
            "checkpoint_prefix": checkpoint_prefix,
            "scenario_key": scenario_key,
            "scenario_generation": scenario_generation,
        },
    )

    # Update scenario state to PROCESSING if applicable
    if scenario_key:
        db.execute(
            text("UPDATE DemoScenarioState SET lifecycle_state = 'PROCESSING', active_run_id = :rid, updated_at = NOW() WHERE scenario_key = :key"),
            {"rid": run_id, "key": scenario_key},
        )

    db.commit()

    job_params = {"batch_id": batch_id, "case_id": str(case_id), "run_id": run_id, "phase": "extract"}
    if scenario_key:
        job_params["scenario_key"] = scenario_key
        job_params["scenario_generation"] = str(scenario_generation or 0)

    submission = submit_ingestion_job(
        db,
        run_id=run_id,
        params=job_params,
    )
    db.commit()
    logger.info("job submitted run_id=%s job_id=%s queue_status=%s", run_id, submission.job_id, submission.queue_status)

    return ProcessBatchResponse(
        run_id=run_id,
        case_id=case_id,
        batch_id=batch_id,
        phase="EXTRACT",
        status="QUEUED" if submission.queue_status != "FAILED" else "FAILED",
        job_id=submission.job_id,
    )


@router.post("/process/{run_id}/proceed", response_model=ProcessProceedResponse)
def process_proceed(run_id: str, db: Session = Depends(get_db)) -> ProcessProceedResponse:
    run = db.execute(
        text("SELECT run_id, batch_id, case_id, status, scenario_key, scenario_generation FROM PipelineRun WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).mappings().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found.")
    if run["status"] != "REVIEW_PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Run is not awaiting review (status={run['status']}).",
        )

    # Block proceed if unresolved review items remain
    pending = db.execute(
        text("SELECT count(*) AS cnt FROM ReviewQueueItem WHERE source_run_id = :rid AND status = 'pending'"),
        {"rid": run_id},
    ).mappings().one()
    if pending["cnt"] > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Resolve all {pending['cnt']} pending review items before proceeding.",
        )

    db.execute(
        text("UPDATE PipelineRun SET phase = 'LOAD', current_stage = 'QUEUED', updated_at = NOW() WHERE run_id = :run_id"),
        {"run_id": run_id},
    )
    db.commit()

    job_params = {
        "batch_id": str(run["batch_id"]),
        "case_id": str(run["case_id"]),
        "run_id": run_id,
        "phase": "load",
    }
    if run["scenario_key"]:
        job_params["scenario_key"] = run["scenario_key"]
        job_params["scenario_generation"] = str(run["scenario_generation"] or 0)

    submission = submit_ingestion_job(
        db,
        run_id=run_id,
        params=job_params,
    )
    db.commit()

    return ProcessProceedResponse(
        run_id=run_id,
        phase="LOAD",
        status="QUEUED" if submission.queue_status != "FAILED" else "FAILED",
        job_id=submission.job_id,
    )


@router.post("/process/{run_id}/retry", response_model=ProcessProceedResponse)
def process_retry(run_id: str, db: Session = Depends(get_db)) -> ProcessProceedResponse:
    """Re-submit a failed run's current phase. Safe to retry: raw/ files survive
    a Phase A failure, the processed/ checkpoint survives a Phase B failure, and
    both phases are idempotent (MERGE-keyed graph writes, checkpoint overwrite)."""
    run = db.execute(
        text("SELECT run_id, batch_id, case_id, phase, status FROM PipelineRun WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).mappings().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found.")
    if run["status"] != "FAILED":
        raise HTTPException(status_code=400, detail=f"Only a failed run can be retried (status={run['status']}).")

    phase_to_job = {"EXTRACT": "extract", "REVIEW": "extract", "LOAD": "load", "DONE": "load"}
    job_phase = phase_to_job.get(run["phase"], "extract")
    friendly_phase = "EXTRACT" if job_phase == "extract" else "LOAD"

    db.execute(
        text(
            """
            UPDATE PipelineRun
            SET status = 'QUEUED', current_stage = 'QUEUED', error_message = NULL, error_stage = NULL, updated_at = NOW()
            WHERE run_id = :run_id
            """
        ),
        {"run_id": run_id},
    )
    db.commit()

    submission = submit_ingestion_job(
        db,
        run_id=run_id,
        params={"batch_id": str(run["batch_id"]), "case_id": str(run["case_id"]), "run_id": run_id, "phase": job_phase},
    )
    db.commit()

    return ProcessProceedResponse(
        run_id=run_id,
        phase=friendly_phase,
        status="QUEUED" if submission.queue_status != "FAILED" else "FAILED",
        job_id=submission.job_id,
    )


@router.get("/process/{run_id}/findings")
def get_findings(run_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    """What was found in the uploaded documents — people, accounts, the money
    trail, and how they connect — for the reviewer to read before clicking Proceed."""
    run = db.execute(
        text("SELECT run_id, case_id, batch_id, phase, status, checkpoint_prefix FROM PipelineRun WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).mappings().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found.")
    if not run["checkpoint_prefix"] or run["phase"] == "EXTRACT":
        raise HTTPException(
            status_code=409,
            detail=f"Still processing this upload ({status_label(run['status'])}). Findings will be ready once review starts.",
        )

    try:
        manifest = get_checkpoint_manifest(int(run["case_id"]), run_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not read the saved findings for this run: {exc}") from exc

    return build_findings(db, run=dict(run), manifest=manifest)
