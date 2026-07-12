from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..demo_scenarios import SCENARIO_ALLOWLIST
from ..schemas import UploadResponse, UploadResponseItem
from ..services.catalyst_queue import build_raw_key, list_raw_objects, upload_file_to_stratus
from ..services.stage_labels import annotate_run


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])

_FILE_TYPE_TO_DOC_TYPE = {"fir": "FIR", "ir": "IR"}


def _get_doc_constraints(db: Session, doc_type: str | None) -> tuple[set[str], int]:
    if doc_type is None:
        return set(settings.default_allowed_exts), settings.default_max_file_mb

    row = db.execute(
        text(
            """
            SELECT allowed_file_extensions, max_file_size_mb
            FROM SchemaDefinition
            WHERE doc_type = :doc_type AND is_active = true
            ORDER BY version DESC
            LIMIT 1
            """
        ),
        {"doc_type": doc_type},
    ).mappings().first()

    if not row:
        return set(settings.default_allowed_exts), settings.default_max_file_mb

    allowed_raw = str(row["allowed_file_extensions"] or "")
    allowed = {ext.strip().lower() for ext in allowed_raw.split(",") if ext.strip()}
    if not allowed:
        allowed = set(settings.default_allowed_exts)
    max_mb = int(row["max_file_size_mb"] or settings.default_max_file_mb)
    return allowed, max_mb


@router.post("", response_model=UploadResponse)
async def upload_documents(
    files: list[UploadFile] = File(...),
    file_types: list[str] = Form(...),
    case_id: int | None = Form(default=None),
    uploaded_by: str | None = Form(default=None),
    scenario_key: str | None = Form(default=None),
    scenario_generation: int | None = Form(default=None),
    reset_token: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> UploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")
    if len(files) != len(file_types):
        raise HTTPException(status_code=400, detail="file_types must have one entry per file.")
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(
            status_code=400,
            detail=f"You can upload up to {settings.max_files_per_upload} files at a time. Please split this into smaller batches.",
        )

    normalized_types = [ft.strip().lower() for ft in file_types]
    for ft in normalized_types:
        if ft not in ("fir", "ir", "evidence"):
            raise HTTPException(status_code=400, detail=f"'{ft}' is not a recognised document type. Choose FIR, IR, or Evidence.")

    # Scenario fencing: validate generation is current and state is READY
    if scenario_key:
        if scenario_key not in SCENARIO_ALLOWLIST:
            raise HTTPException(status_code=400, detail=f"Unknown scenario: {scenario_key}")
        state = db.execute(
            text("SELECT generation, lifecycle_state FROM DemoScenarioState WHERE scenario_key = :key"),
            {"key": scenario_key},
        ).mappings().first()
        if not state:
            raise HTTPException(status_code=409, detail="Scenario not prepared. Call prepare first.")
        if state["lifecycle_state"] not in ("READY",):
            raise HTTPException(status_code=409, detail=f"Scenario is not ready for upload (state={state['lifecycle_state']}).")
        if scenario_generation is not None and state["generation"] != scenario_generation:
            raise HTTPException(status_code=409, detail="Stale scenario generation. Re-prepare the scenario.")
        # Claim READY -> UPLOADING
        db.execute(
            text("UPDATE DemoScenarioState SET lifecycle_state = 'UPLOADING', updated_at = NOW() WHERE scenario_key = :key AND lifecycle_state = 'READY'"),
            {"key": scenario_key},
        )
        db.flush()

    # For new cases with a scenario, allow mixed FIR/IR/evidence.
    # For custom new cases, still require at least one FIR.
    if case_id is None and not scenario_key:
        if "fir" not in normalized_types:
            raise HTTPException(status_code=400, detail="A new case must include at least one FIR.")

    max_total_bytes = settings.max_total_upload_mb * 1024 * 1024

    batch_id = str(uuid.uuid4())
    logger.info("upload batch_id=%s case_id=%s scenario=%s files=%d", batch_id, case_id, scenario_key, len(files))
    db.execute(
        text(
            """
            INSERT INTO BatchUpload (batch_id, case_id, uploaded_by, scenario_key, scenario_generation, created_at)
            VALUES (:batch_id, :case_id, :uploaded_by, :scenario_key, :scenario_generation, NOW())
            """
        ),
        {
            "batch_id": batch_id,
            "case_id": case_id,
            "uploaded_by": uploaded_by,
            "scenario_key": scenario_key,
            "scenario_generation": scenario_generation,
        },
    )
    db.commit()

    results: list[UploadResponseItem] = []
    total_bytes = 0
    for upload, file_type in zip(files, normalized_types):
        allowed_exts, max_file_mb = _get_doc_constraints(db, doc_type=_FILE_TYPE_TO_DOC_TYPE.get(file_type))
        max_file_bytes = max_file_mb * 1024 * 1024

        ext = (upload.filename or "").split(".")[-1].lower() if upload.filename else ""
        if ext not in allowed_exts:
            results.append(
                UploadResponseItem(
                    filename=upload.filename or "<unknown>",
                    file_type=file_type,
                    status="FAILED",
                    message=f"This file type (.{ext or 'unknown'}) is not supported. Accepted: {', '.join(sorted(allowed_exts))}.",
                )
            )
            continue

        data = await upload.read()
        total_bytes += len(data)
        if total_bytes > max_total_bytes:
            results.append(
                UploadResponseItem(
                    filename=upload.filename or "<unknown>",
                    file_type=file_type,
                    status="FAILED",
                    message=f"This upload is too large overall (limit {settings.max_total_upload_mb} MB per batch). Try uploading in smaller batches.",
                )
            )
            continue
        if len(data) > max_file_bytes:
            results.append(
                UploadResponseItem(
                    filename=upload.filename or "<unknown>",
                    file_type=file_type,
                    status="FAILED",
                    message=f"This file is larger than the {max_file_mb} MB limit for {file_type} documents.",
                )
            )
            continue

        raw_key = build_raw_key(batch_id=batch_id, file_type=file_type, filename=upload.filename or "file")
        try:
            upload_file_to_stratus(raw_key, data)
            logger.info("stratus upload ok key=%s size=%d", raw_key, len(data))
        except Exception as exc:
            logger.exception("stratus upload failed key=%s: %s", raw_key, exc)
            results.append(
                UploadResponseItem(
                    filename=upload.filename or "<unknown>",
                    file_type=file_type,
                    status="FAILED",
                    message=f"Stratus upload failed: {exc}",
                )
            )
            continue

        results.append(
            UploadResponseItem(
                filename=upload.filename or "<unknown>",
                file_type=file_type,
                status="STORED",
                stratus_key=raw_key,
            )
        )

    return UploadResponse(batch_id=batch_id, case_id=case_id, files=results)


@router.get("/{batch_id}")
def get_batch(batch_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    """Rediscover a batch's stored files and any processing runs started for it
    (used by the FE to recover state after a page refresh)."""
    batch = db.execute(
        text("SELECT batch_id, case_id, uploaded_by, created_at FROM BatchUpload WHERE batch_id = :batch_id"),
        {"batch_id": batch_id},
    ).mappings().first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")

    files = [
        {"key": entry["key"], "filename": entry["key"].rsplit("/", 1)[-1]}
        for entry in list_raw_objects(batch_id)
    ]
    runs = db.execute(
        text(
            """
            SELECT run_id, case_id, phase, current_stage, status, created_at, updated_at
            FROM PipelineRun
            WHERE batch_id = :batch_id
            ORDER BY created_at DESC
            """
        ),
        {"batch_id": batch_id},
    ).mappings().all()

    return {**dict(batch), "files": files, "runs": [annotate_run(dict(r)) for r in runs]}
