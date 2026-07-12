from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CaseCreateRequest(BaseModel):
    case_master_id: int | None = None
    crime_no: str
    case_no: str
    crime_registered_date: date
    police_person_id: int
    police_station_id: int
    case_category_id: int
    gravity_offence_id: int
    crime_major_head_id: int
    crime_minor_head_id: int
    case_status_id: int
    court_id: int
    brief_facts: str | None = None


class CaseResponse(BaseModel):
    case_master_id: int
    crime_no: str | None = None
    case_no: str | None = None
    crime_registered_date: datetime | date | str | None = None
    police_station_id: int | None = None
    case_status_id: int | None = None
    brief_facts: str | None = None


class UploadResponseItem(BaseModel):
    filename: str
    file_type: str
    status: str
    message: str | None = None
    stratus_key: str | None = None


class UploadResponse(BaseModel):
    batch_id: str
    case_id: int | None = None
    files: list[UploadResponseItem]


class ProcessBatchResponse(BaseModel):
    run_id: str
    case_id: int
    batch_id: str
    phase: str
    status: str
    job_id: str | None = None


class ProcessProceedResponse(BaseModel):
    run_id: str
    phase: str
    status: str
    job_id: str | None = None


class SchemaFieldPayload(BaseModel):
    group_name: str
    is_repeating_group: bool = False
    pole_entity_type: str | None = None
    field_name: str
    data_type: str
    is_required: bool = False
    target_table: str
    target_column: str
    is_identifier: bool = False
    identifier_type: str | None = None
    extraction_hint: str | None = None
    display_order: int | None = None


class SchemaRelationshipPayload(BaseModel):
    from_group: str
    to_group: str
    relationship_type: str
    direction: str = "from_to"
    fixed_edge_properties: dict[str, Any] | None = None
    edge_property_source_fields: list[str] | None = None


class SchemaVersionCreateRequest(BaseModel):
    description: str | None = None
    allowed_file_extensions: list[str] = Field(default_factory=lambda: ["txt", "html", "pdf"])
    max_file_size_mb: int = 15
    fields: list[SchemaFieldPayload] = Field(default_factory=list)
    relationships: list[SchemaRelationshipPayload] = Field(default_factory=list)
    created_by: str | None = None


class ReviewResolveRequest(BaseModel):
    decision: Literal["merge", "keep_separate"]
    resolved_by: str | None = None
    # Required only when decision == merge and candidate uid is not in JSON payload.
    candidate_entity_uid: str | None = None


class SplinkMatchRequest(BaseModel):
    source_run_id: str | None = None
    candidate_record: dict[str, Any]
    existing_records: list[dict[str, Any]]
    entity_type: str = "Person"
    persist_review_items: bool = False
    match_against_entity_uids: list[str] | None = None


class ThresholdUpdateRequest(BaseModel):
    value: float = Field(ge=0.0, le=1.0)
    updated_by: str | None = None


class AdminConfigUpdateRequest(BaseModel):
    value: str
    updated_by: str | None = None


# --- Demo scenario models ---


class ScenarioPrepareResponse(BaseModel):
    scenario_key: str
    generation: int
    reset_token: str
    status: str


class ScenarioStateResponse(BaseModel):
    scenario_key: str
    crime_no: str
    generation: int
    lifecycle_state: str
    error_message: str | None = None

