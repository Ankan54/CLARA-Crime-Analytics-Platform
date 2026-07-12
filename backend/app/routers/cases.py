from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import CaseCreateRequest, CaseResponse
from ..services.stage_labels import annotate_run

logger = logging.getLogger(__name__)

_CASE_SELECT = """
    SELECT
        CaseMasterID AS case_master_id,
        CrimeNo AS crime_no,
        CaseNo AS case_no,
        CrimeRegisteredDate AS crime_registered_date,
        PoliceStationID AS police_station_id,
        CaseStatusID AS case_status_id,
        BriefFacts AS brief_facts
    FROM CaseMaster
"""


router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CaseResponse)
def create_case(payload: CaseCreateRequest, db: Session = Depends(get_db)) -> CaseResponse:
    logger.info("create_case start case_master_id=%s crime_no=%s", payload.case_master_id, payload.crime_no)
    case_master_id = payload.case_master_id
    if case_master_id is None:
        row = db.execute(text("SELECT COALESCE(MAX(CaseMasterID), 0) + 1 AS next_id FROM CaseMaster")).mappings().one()
        case_master_id = int(row["next_id"])

    try:
        db.execute(
            text(
                """
                INSERT INTO CaseMaster
                (
                    CaseMasterID, CrimeNo, CaseNo, CrimeRegisteredDate, PolicePersonID,
                    PoliceStationID, CaseCategoryID, GravityOffenceID, CrimeMajorHeadID,
                    CrimeMinorHeadID, CaseStatusID, CourtID, BriefFacts
                )
                VALUES
                (
                    :case_master_id, :crime_no, :case_no, :crime_registered_date, :police_person_id,
                    :police_station_id, :case_category_id, :gravity_offence_id, :crime_major_head_id,
                    :crime_minor_head_id, :case_status_id, :court_id, :brief_facts
                )
                """
            ),
            {
                "case_master_id": case_master_id,
                "crime_no": payload.crime_no,
                "case_no": payload.case_no,
                "crime_registered_date": payload.crime_registered_date.isoformat(),
                "police_person_id": payload.police_person_id,
                "police_station_id": payload.police_station_id,
                "case_category_id": payload.case_category_id,
                "gravity_offence_id": payload.gravity_offence_id,
                "crime_major_head_id": payload.crime_major_head_id,
                "crime_minor_head_id": payload.crime_minor_head_id,
                "case_status_id": payload.case_status_id,
                "court_id": payload.court_id,
                "brief_facts": payload.brief_facts,
            },
        )
        db.commit()
    except Exception as exc:
        logger.exception("create_case failed case_master_id=%s crime_no=%s", case_master_id, payload.crime_no)
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create case: {exc}") from exc

    row = db.execute(text(_CASE_SELECT + " WHERE CaseMasterID = :case_master_id"), {"case_master_id": case_master_id}).mappings().one()
    logger.info("create_case done case_master_id=%s", case_master_id)
    return CaseResponse(**dict(row))


@router.get("", response_model=list[CaseResponse])
def list_cases(
    query: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[CaseResponse]:
    logger.info("list_cases start query=%s limit=%s", query, limit)
    sql = _CASE_SELECT
    params: dict[str, object] = {"limit": limit}
    if query:
        sql += " WHERE CrimeNo ILIKE :q OR CaseNo ILIKE :q OR BriefFacts ILIKE :q"
        params["q"] = f"%{query}%"
    sql += " ORDER BY CaseMasterID DESC LIMIT :limit"
    rows = db.execute(text(sql), params).mappings().all()
    logger.info("list_cases done query=%s count=%d", query, len(rows))
    return [CaseResponse(**dict(row)) for row in rows]


@router.get("/{case_id}")
def get_case(case_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    logger.info("get_case start case_id=%s", case_id)
    row = db.execute(text(_CASE_SELECT + " WHERE CaseMasterID = :case_id"), {"case_id": case_id}).mappings().first()
    if row is None:
        logger.warning("get_case not found case_id=%s", case_id)
        raise HTTPException(status_code=404, detail="Case not found.")

    counts = db.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*) FROM Accused WHERE CaseMasterID = :case_id) AS accused,
                (SELECT COUNT(*) FROM Victim WHERE CaseMasterID = :case_id) AS victims,
                (SELECT COUNT(*) FROM ComplainantDetails WHERE CaseMasterID = :case_id) AS complainants,
                (SELECT COUNT(*) FROM Evidence WHERE case_id = :case_id) AS evidence,
                (SELECT COUNT(*) FROM InvestigationReport WHERE case_id = :case_id) AS investigation_reports
            """
        ),
        {"case_id": case_id},
    ).mappings().one()

    runs = db.execute(
        text(
            """
            SELECT run_id, batch_id, phase, current_stage, status, created_at, updated_at
            FROM PipelineRun WHERE case_id = :case_id ORDER BY created_at DESC LIMIT 20
            """
        ),
        {"case_id": case_id},
    ).mappings().all()

    logger.info("get_case done case_id=%s runs=%d", case_id, len(runs))
    return {**dict(row), "counts": dict(counts), "runs": [annotate_run(dict(r)) for r in runs]}

