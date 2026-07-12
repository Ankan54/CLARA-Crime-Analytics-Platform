from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import AdminConfigUpdateRequest, ReviewResolveRequest, ThresholdUpdateRequest
from ..services.entity_resolution import manual_merge_entities, match_reasons, resolve_person_record

logger = logging.getLogger(__name__)

router = APIRouter(tags=["review"])


def _read_threshold(db: Session) -> float:
    logger.debug("review _read_threshold start")
    row = db.execute(
        text("SELECT config_value FROM AppConfig WHERE config_key = 'entity_review_threshold'")
    ).mappings().first()
    if row is None:
        logger.debug("review _read_threshold default=0.8 (missing row)")
        return 0.8
    try:
        value = float(row["config_value"])
        logger.debug("review _read_threshold value=%s", value)
        return value
    except (TypeError, ValueError):
        logger.warning("review _read_threshold invalid value=%s; using default 0.8", row.get("config_value"))
        return 0.8


@router.get("/api/v1/review-queue")
def list_review_queue(
    status: str = Query(default="pending"),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    logger.info("list_review_queue start status=%s run_id=%s limit=%s", status, run_id, limit)
    threshold = _read_threshold(db)
    rows = db.execute(
        text(
            """
            SELECT review_id, source_run_id, entity_type, candidate_record_json, matched_against_entity_uid,
                   match_score, matched_fields_json, status, resolved_by, resolved_at, created_at
            FROM ReviewQueueItem
            WHERE status = :status
              AND (:run_id IS NULL OR source_run_id = :run_id)
            ORDER BY created_at ASC
            LIMIT :limit
            """
        ),
        {"status": status, "run_id": run_id, "limit": limit},
    ).mappings().all()

    items = []
    for row in rows:
        item = dict(row)
        candidate = json.loads(item["candidate_record_json"] or "{}")
        matched_fields = json.loads(item["matched_fields_json"] or "[]")
        item["candidate_record_json"] = candidate
        item["matched_fields_json"] = matched_fields
        item["candidate_name"] = candidate.get("name")
        item["matched_record"] = resolve_person_record(db, str(item["matched_against_entity_uid"]))
        item["match_reasons"] = match_reasons(matched_fields)
        item["colour"] = "green" if float(item["match_score"]) >= threshold else "red"
        items.append(item)
    logger.info("list_review_queue done status=%s run_id=%s count=%d", status, run_id, len(items))
    return {"threshold": threshold, "count": len(items), "items": items}


@router.post("/api/v1/review-queue/{review_id}/resolve")
def resolve_review_item(
    review_id: int,
    payload: ReviewResolveRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    logger.info("resolve_review_item start review_id=%s decision=%s", review_id, payload.decision)
    row = db.execute(
        text(
            """
            SELECT r.review_id, r.candidate_record_json, r.matched_against_entity_uid, r.status,
                   p.phase AS run_phase
            FROM ReviewQueueItem r
            JOIN PipelineRun p ON p.run_id = r.source_run_id
            WHERE r.review_id = :review_id
            """
        ),
        {"review_id": review_id},
    ).mappings().first()
    if row is None:
        logger.warning("resolve_review_item not found review_id=%s", review_id)
        raise HTTPException(status_code=404, detail="Review item not found.")
    if row["status"] != "pending":
        logger.warning("resolve_review_item already resolved review_id=%s status=%s", review_id, row["status"])
        raise HTTPException(status_code=400, detail="Review item is already resolved.")

    status = "kept_separate"
    if payload.decision == "merge":
        candidate_json = json.loads(row["candidate_record_json"] or "{}")
        losing_uid = payload.candidate_entity_uid or candidate_json.get("entity_uid")
        winning_uid = row["matched_against_entity_uid"]
        if not losing_uid or not winning_uid:
            raise HTTPException(
                status_code=400,
                detail="Merge needs both candidate_entity_uid and matched_against_entity_uid.",
            )
        # Before Phase B loads it, the "candidate" is only a provisional uid checkpointed in
        # Stratus, not yet a row in any store — merging live here would touch nothing (or
        # worse, an unrelated pre-existing entity). Just record the decision; Phase B reads
        # it back via _resolve_review_decisions() and remaps the provisional uid at load time.
        if row["run_phase"] not in ("EXTRACT", "REVIEW"):
            logger.info("resolve_review_item applying manual merge review_id=%s losing_uid=%s winning_uid=%s", review_id, losing_uid, winning_uid)
            manual_merge_entities(db, losing_uid=losing_uid, winning_uid=winning_uid)
        status = "merged"

    db.execute(
        text(
            """
            UPDATE ReviewQueueItem
            SET status = :status,
                resolved_by = :resolved_by,
                resolved_at = NOW()
            WHERE review_id = :review_id
            """
        ),
        {"status": status, "resolved_by": payload.resolved_by, "review_id": review_id},
    )
    db.commit()
    logger.info("resolve_review_item done review_id=%s status=%s", review_id, status)
    return {"review_id": review_id, "status": status}


@router.get("/api/v1/admin/config")
def list_admin_config(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    logger.info("list_admin_config start")
    rows = db.execute(
        text("SELECT config_key, config_value, updated_by, updated_at FROM AppConfig ORDER BY config_key")
    ).mappings().all()
    logger.info("list_admin_config done count=%d", len(rows))
    return [dict(row) for row in rows]


@router.get("/api/v1/admin/config/entity-review-threshold")
def get_entity_review_threshold(db: Session = Depends(get_db)) -> dict[str, object]:
    logger.info("get_entity_review_threshold")
    return {"config_key": "entity_review_threshold", "value": _read_threshold(db)}


@router.put("/api/v1/admin/config/entity-review-threshold")
def update_entity_review_threshold(payload: ThresholdUpdateRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    logger.info("update_entity_review_threshold value=%s updated_by=%s", payload.value, payload.updated_by)
    db.execute(
        text(
            """
            INSERT INTO AppConfig(config_key, config_value, updated_by, updated_at)
            VALUES ('entity_review_threshold', :value, :updated_by, NOW())
            ON CONFLICT (config_key)
            DO UPDATE SET
                config_value = EXCLUDED.config_value,
                updated_by = EXCLUDED.updated_by,
                updated_at = EXCLUDED.updated_at
            """
        ),
        {"value": str(payload.value), "updated_by": payload.updated_by},
    )
    db.commit()
    logger.info("update_entity_review_threshold done value=%s", payload.value)
    return {"config_key": "entity_review_threshold", "value": payload.value}


@router.put("/api/v1/admin/config/{config_key}")
def update_admin_config(config_key: str, payload: AdminConfigUpdateRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    """Generic upsert for any AppConfig key. Registered after the specific
    entity-review-threshold route above, which FastAPI matches first for that
    exact path (kept for backwards-compatible 0.0-1.0 validation)."""
    logger.info("update_admin_config key=%s updated_by=%s", config_key, payload.updated_by)
    db.execute(
        text(
            """
            INSERT INTO AppConfig(config_key, config_value, updated_by, updated_at)
            VALUES (:config_key, :value, :updated_by, NOW())
            ON CONFLICT (config_key)
            DO UPDATE SET
                config_value = EXCLUDED.config_value,
                updated_by = EXCLUDED.updated_by,
                updated_at = EXCLUDED.updated_at
            """
        ),
        {"config_key": config_key, "value": payload.value, "updated_by": payload.updated_by},
    )
    db.commit()
    logger.info("update_admin_config done key=%s", config_key)
    return {"config_key": config_key, "value": payload.value}

