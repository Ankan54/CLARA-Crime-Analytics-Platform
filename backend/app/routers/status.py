from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, get_db
from ..services.pipeline_broadcast import subscribe, unsubscribe
from ..services.run_watchdog import reap_stale_runs
from ..services.stage_labels import annotate_run

logger = logging.getLogger(__name__)

router = APIRouter(tags=["status"])

_TERMINAL_STATUSES = {"COMPLETED", "COMPLETED_WITH_REVIEW_PENDING", "FAILED"}

_RUN_STATUS_QUERY = """
    SELECT run_id, batch_id, case_id, phase, checkpoint_prefix, files_progress,
           current_stage, status, error_stage, error_message, scenario_key, scenario_generation,
           created_at, updated_at
    FROM PipelineRun
    WHERE run_id = :run_id
"""


@router.get("/api/v1/pipeline-status/{run_id}")
def get_pipeline_status(run_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    logger.info("get_pipeline_status run_id=%s", run_id)
    reap_stale_runs(db, run_id=run_id)
    row = db.execute(text(_RUN_STATUS_QUERY), {"run_id": run_id}).mappings().first()
    if row is None:
        logger.warning("get_pipeline_status run not found run_id=%s", run_id)
        return {"run_id": run_id, "status": "NOT_FOUND", "status_label": "Not found"}
    result = annotate_run(dict(row))

    # Add review_required flag and pending count
    if row["status"] in ("REVIEW_PENDING", "COMPLETED_WITH_REVIEW_PENDING"):
        pending = db.execute(
            text("SELECT count(*) AS cnt FROM ReviewQueueItem WHERE source_run_id = :rid AND status = 'pending'"),
            {"rid": run_id},
        ).mappings().one()
        result["review_required"] = pending["cnt"] > 0
        result["pending_review_count"] = pending["cnt"]
    else:
        result["review_required"] = False
        result["pending_review_count"] = 0

    logger.debug("get_pipeline_status run_id=%s status=%s stage=%s", run_id, row.get("status"), row.get("current_stage"))
    return result


def _fetch_run(run_id: str) -> dict[str, object] | None:
    logger.debug("status _fetch_run run_id=%s", run_id)
    db = SessionLocal()
    try:
        reap_stale_runs(db, run_id=run_id)
        row = db.execute(text(_RUN_STATUS_QUERY), {"run_id": run_id}).mappings().first()
        return annotate_run(dict(row)) if row else None
    except Exception:
        logger.exception("status _fetch_run failed run_id=%s", run_id)
        raise
    finally:
        db.close()


@router.websocket("/ws/pipeline/{run_id}")
async def ws_pipeline_status(websocket: WebSocket, run_id: str) -> None:
    """Streams the PipelineRun row (incl. files_progress) for one run.
    REVIEW_PENDING is not a terminal status: the stream stays open and idles
    there until Proceed kicks off Phase B. Push-first via the Signals webhook
    broadcast; falls back to a plain Postgres poll every ws_poll_seconds so a
    missed/duplicate Signals delivery or a slow webhook still gets picked up."""
    logger.info("ws_pipeline_status connect run_id=%s", run_id)
    await websocket.accept()
    queue = subscribe(run_id)
    last_payload = ""
    try:
        while True:
            row = _fetch_run(run_id)
            if row is None:
                logger.warning("ws_pipeline_status run not found run_id=%s", run_id)
                await websocket.send_json({"run_id": run_id, "status": "NOT_FOUND"})
                break

            payload = json.dumps(row, default=str)
            if payload != last_payload:
                await websocket.send_json(json.loads(payload))
                last_payload = payload

            if row["status"] in _TERMINAL_STATUSES:
                logger.info("ws_pipeline_status terminal status run_id=%s status=%s", run_id, row["status"])
                break

            try:
                await asyncio.wait_for(queue.get(), timeout=settings.ws_poll_seconds)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        logger.info("ws_pipeline_status disconnected run_id=%s", run_id)
        return
    except Exception as exc:
        logger.exception("ws_pipeline_status failed run_id=%s", run_id)
        await websocket.send_json({"run_id": run_id, "error": str(exc)})
    finally:
        unsubscribe(run_id, queue)
        logger.info("ws_pipeline_status closing run_id=%s", run_id)
        await websocket.close()
