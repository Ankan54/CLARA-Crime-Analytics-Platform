"""Router for demo scenario prepare/reset and state queries."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..demo_scenarios import SCENARIO_ALLOWLIST, get_crime_no
from ..schemas import ScenarioPrepareResponse, ScenarioStateResponse
from ..services.demo_scenario_reset import ResetError, prepare_scenario

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo-scenarios", tags=["demo-scenarios"])


@router.get("")
def list_scenarios(db: Session = Depends(get_db)) -> list[dict]:
    """Return the allowlisted scenarios with current state."""
    results = []
    for key, mapping in SCENARIO_ALLOWLIST.items():
        state_row = db.execute(
            text("SELECT generation, lifecycle_state, error_message FROM DemoScenarioState WHERE scenario_key = :key"),
            {"key": key},
        ).mappings().first()

        results.append({
            "scenario_key": key,
            "label": mapping.label,
            "crime_no": mapping.crime_no,
            "generation": state_row["generation"] if state_row else 0,
            "lifecycle_state": state_row["lifecycle_state"] if state_row else "IDLE",
            "error_message": state_row["error_message"] if state_row else None,
        })
    return results


@router.get("/{scenario_key}")
def get_scenario_state(scenario_key: str, db: Session = Depends(get_db)) -> ScenarioStateResponse:
    """Get state for a specific scenario."""
    if scenario_key not in SCENARIO_ALLOWLIST:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_key}")

    crime_no = get_crime_no(scenario_key) or ""
    state_row = db.execute(
        text("SELECT generation, lifecycle_state, error_message FROM DemoScenarioState WHERE scenario_key = :key"),
        {"key": scenario_key},
    ).mappings().first()

    return ScenarioStateResponse(
        scenario_key=scenario_key,
        crime_no=crime_no,
        generation=state_row["generation"] if state_row else 0,
        lifecycle_state=state_row["lifecycle_state"] if state_row else "IDLE",
        error_message=state_row["error_message"] if state_row else None,
    )


@router.post("/{scenario_key}/prepare", response_model=ScenarioPrepareResponse)
def prepare_scenario_endpoint(
    scenario_key: str,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> ScenarioPrepareResponse:
    """Prepare a scenario for re-ingestion: increment generation, purge old data."""
    if scenario_key not in SCENARIO_ALLOWLIST:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_key}")

    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required.")

    try:
        result = prepare_scenario(db, scenario_key, idempotency_key)
    except ResetError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return ScenarioPrepareResponse(
        scenario_key=result["scenario_key"],
        generation=result["generation"],
        reset_token=result["reset_token"],
        status=result["status"],
    )
