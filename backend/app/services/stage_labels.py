from __future__ import annotations

from typing import Any

# Plain-language labels for a Karnataka Police officer, not a developer — every
# code below is a PipelineRun.current_stage / files_progress[file].stage value
# emitted by catalyst_functions/ingest_processor/pipeline/processor.py.
STAGE_LABELS: dict[str, str] = {
    "QUEUED": "Waiting to start",
    "EXTRACT_START": "Getting started",
    "FETCHING_FILE": "Opening the document",
    "EXTRACTING_TEXT": "Reading the document",
    "CLASSIFYING": "Identifying the document type",
    "LOADING_SCHEMA": "Preparing to read this document",
    "STRUCTURED_EXTRACT": "Picking out names, numbers and accounts",
    "TRANSFORM": "Organising the details found",
    "ENTITY_MATCH": "Checking against people already on record",
    "CHECKPOINTED": "Saved for review",
    "WRITING_CHECKPOINT": "Wrapping up this step",
    "EXTRACT_DONE": "Finished reading the documents",
    "REVIEW_PENDING": "Ready for your review",
    "LOAD_START": "Starting to save the case",
    "SQL_LOAD": "Saving to case records",
    "GRAPH_LOAD": "Connecting into the case network",
    "VECTOR_LOAD": "Indexing for smart search",
    "WRITEBACK": "Cross-linking records",
    "FILE_DONE": "Finished with this file",
    "ARCHIVING": "Filing away the original documents",
    "DONE": "Completed",
}

STATUS_LABELS: dict[str, str] = {
    "QUEUED": "Waiting to start",
    "RUNNING": "In progress",
    "REVIEW_PENDING": "Ready for your review",
    "COMPLETED": "Completed",
    "COMPLETED_WITH_REVIEW_PENDING": "Completed \u2014 some matches need your review",
    "FAILED": "Something went wrong",
}


def _label(code: Any, table: dict[str, str]) -> str:
    if not code:
        return ""
    code = str(code)
    return table.get(code, code.replace("_", " ").strip().title())


def stage_label(code: Any) -> str:
    return _label(code, STAGE_LABELS)


def status_label(code: Any) -> str:
    return _label(code, STATUS_LABELS)


def annotate_run(row: dict[str, Any]) -> dict[str, Any]:
    """Attach *_label fields to a PipelineRun row and each files_progress entry,
    for direct rendering in the UI. Raw codes are left untouched for FE logic."""
    row = dict(row)
    row["stage_label"] = stage_label(row.get("current_stage"))
    row["status_label"] = status_label(row.get("status"))

    files_progress = row.get("files_progress") or {}
    if isinstance(files_progress, dict):
        annotated: dict[str, Any] = {}
        for filename, entry in files_progress.items():
            entry = dict(entry) if isinstance(entry, dict) else {"stage": entry}
            entry["stage_label"] = stage_label(entry.get("stage"))
            entry["status_label"] = status_label(entry.get("status"))
            annotated[filename] = entry
        row["files_progress"] = annotated

    return row
