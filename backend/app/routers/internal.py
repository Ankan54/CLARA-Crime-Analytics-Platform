from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..schemas import SplinkMatchRequest
from ..services.entity_resolution import create_review_queue_items, score_person_candidates
from ..services.pipeline_broadcast import is_duplicate_event, publish

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/entity/splink-match")
def splink_match_endpoint(
    payload: SplinkMatchRequest,
    x_splink_secret: str = Header(default=""),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    logger.info(
        "splink_match_endpoint start run_id=%s entity_type=%s persist=%s existing_records=%d",
        payload.source_run_id,
        payload.entity_type,
        payload.persist_review_items,
        len(payload.existing_records),
    )
    if x_splink_secret != settings.splink_shared_secret:
        logger.warning("splink_match_endpoint forbidden: invalid secret run_id=%s", payload.source_run_id)
        raise HTTPException(status_code=403, detail="Invalid Splink shared secret.")

    # Reject stale scenario generations
    if payload.source_run_id:
        run_row = db.execute(
            text("SELECT scenario_key, scenario_generation FROM PipelineRun WHERE run_id = :rid"),
            {"rid": payload.source_run_id},
        ).mappings().first()
        if run_row and run_row["scenario_key"]:
            state = db.execute(
                text("SELECT generation FROM DemoScenarioState WHERE scenario_key = :key"),
                {"key": run_row["scenario_key"]},
            ).mappings().first()
            if state and run_row["scenario_generation"] is not None and state["generation"] > run_row["scenario_generation"]:
                logger.warning("splink_match_endpoint rejected stale generation run_id=%s", payload.source_run_id)
                raise HTTPException(status_code=409, detail="Stale scenario generation. This run has been superseded.")

    matches = score_person_candidates(payload.candidate_record, payload.existing_records)
    if payload.match_against_entity_uids:
        allow = set(payload.match_against_entity_uids)
        matches = [m for m in matches if m.get("matched_against_entity_uid") in allow]
    matches = matches[: settings.splink_match_limit]

    created = 0
    if payload.persist_review_items:
        if not payload.source_run_id:
            logger.warning("splink_match_endpoint missing source_run_id while persist=true")
            raise HTTPException(status_code=400, detail="source_run_id required when persist_review_items=true")
        created = create_review_queue_items(
            db,
            run_id=payload.source_run_id,
            entity_type=payload.entity_type,
            candidate_record=payload.candidate_record,
            matches=matches,
        )
        db.commit()

    logger.info(
        "splink_match_endpoint done run_id=%s matches=%d review_items_created=%d",
        payload.source_run_id,
        len(matches),
        created,
    )
    return {"matches": matches, "review_items_created": created}


@router.post("/pipeline-event")
def pipeline_event_webhook(
    payload: dict[str, Any],
    x_splink_secret: str = Header(default=""),
    token: str = Query(default=""),
) -> dict[str, object]:
    """Signals -> Webhook target for the pipeline-status/stage_update Rule.
    Unwraps the delivery envelope (our fields live at events[].data) and pushes
    each stage_update event into the in-process broadcast for /ws/pipeline/{run_id}."""
    logger.info("pipeline_event_webhook start token_provided=%s events=%d", bool(token), len(payload.get("events") or []))
    if (x_splink_secret or token) != settings.splink_shared_secret:
        logger.warning("pipeline_event_webhook forbidden: invalid secret")
        raise HTTPException(status_code=403, detail="Invalid inbound secret.")

    events = payload.get("events") or []
    delivered = 0
    for event in events:
        if (event.get("event_config") or {}).get("api_name") != "stage_update":
            continue
        if is_duplicate_event(str(event.get("id") or "")):
            continue
        data = event.get("data") or {}
        run_id = data.get("run_id")
        if not run_id:
            continue
        publish(str(run_id), data)
        delivered += 1

    logger.info("pipeline_event_webhook done received=%d delivered=%d", len(events), delivered)
    return {"received": len(events), "delivered": delivered}

