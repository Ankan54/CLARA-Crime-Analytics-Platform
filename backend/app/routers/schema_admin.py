from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import SchemaVersionCreateRequest


router = APIRouter(prefix="/api/v1/admin", tags=["schema-admin"])


def _get_schema_row(db: Session, doc_type: str, version: int | None = None):
    sql = """
        SELECT schema_id, doc_type, version, is_active, description, allowed_file_extensions,
               max_file_size_mb, created_at, created_by
        FROM SchemaDefinition
        WHERE doc_type = :doc_type
    """
    params: dict[str, object] = {"doc_type": doc_type}
    if version is not None:
        sql += " AND version = :version"
        params["version"] = version
    else:
        sql += " AND is_active = true"
    sql += " ORDER BY version DESC LIMIT 1"
    return db.execute(text(sql), params).mappings().first()


@router.get("/schema")
def list_active_schema_versions(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    rows = db.execute(
        text(
            """
            SELECT doc_type, version, schema_id, description, allowed_file_extensions, max_file_size_mb, created_at
            FROM SchemaDefinition
            WHERE is_active = true
            ORDER BY doc_type
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/schema/{doc_type}")
def get_active_schema(doc_type: str, db: Session = Depends(get_db)) -> dict[str, object]:
    schema = _get_schema_row(db, doc_type=doc_type.upper())
    if schema is None:
        raise HTTPException(status_code=404, detail=f"No active schema found for {doc_type}.")
    fields = db.execute(
        text(
            """
            SELECT
                field_id, group_name, is_repeating_group, pole_entity_type, field_name, data_type, is_required,
                target_table, target_column, is_identifier, identifier_type, extraction_hint, display_order
            FROM SchemaField
            WHERE schema_id = :schema_id
            ORDER BY group_name, COALESCE(display_order, 0), field_id
            """
        ),
        {"schema_id": schema["schema_id"]},
    ).mappings().all()
    relationships = db.execute(
        text(
            """
            SELECT
                relationship_id, from_group, to_group, relationship_type, direction,
                fixed_edge_properties, edge_property_source_fields
            FROM SchemaRelationship
            WHERE schema_id = :schema_id
            ORDER BY relationship_id
            """
        ),
        {"schema_id": schema["schema_id"]},
    ).mappings().all()
    return {
        "schema": dict(schema),
        "fields": [dict(row) for row in fields],
        "relationships": [dict(row) for row in relationships],
    }


@router.get("/schema/{doc_type}/versions")
def get_schema_versions(doc_type: str, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    rows = db.execute(
        text(
            """
            SELECT schema_id, doc_type, version, is_active, description, allowed_file_extensions,
                   max_file_size_mb, created_at, created_by
            FROM SchemaDefinition
            WHERE doc_type = :doc_type
            ORDER BY version DESC
            """
        ),
        {"doc_type": doc_type.upper()},
    ).mappings().all()
    return [dict(row) for row in rows]


@router.post("/schema/{doc_type}")
def create_schema_version(
    doc_type: str,
    payload: SchemaVersionCreateRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    doc_type = doc_type.upper()
    max_row = db.execute(
        text("SELECT COALESCE(MAX(version), 0) AS max_version FROM SchemaDefinition WHERE doc_type = :doc_type"),
        {"doc_type": doc_type},
    ).mappings().one()
    next_version = int(max_row["max_version"]) + 1

    schema_id = db.execute(
        text(
            """
            INSERT INTO SchemaDefinition
                (doc_type, version, is_active, description, allowed_file_extensions, max_file_size_mb, created_at, created_by)
            VALUES
                (:doc_type, :version, false, :description, :allowed_file_extensions, :max_file_size_mb, NOW(), :created_by)
            RETURNING schema_id
            """
        ),
        {
            "doc_type": doc_type,
            "version": next_version,
            "description": payload.description,
            "allowed_file_extensions": ",".join(payload.allowed_file_extensions),
            "max_file_size_mb": payload.max_file_size_mb,
            "created_by": payload.created_by,
        },
    ).scalar_one()

    for field in payload.fields:
        db.execute(
            text(
                """
                INSERT INTO SchemaField
                (
                    schema_id, group_name, is_repeating_group, pole_entity_type, field_name, data_type, is_required,
                    target_table, target_column, is_identifier, identifier_type, extraction_hint, display_order
                )
                VALUES
                (
                    :schema_id, :group_name, :is_repeating_group, :pole_entity_type, :field_name, :data_type, :is_required,
                    :target_table, :target_column, :is_identifier, :identifier_type, :extraction_hint, :display_order
                )
                """
            ),
            {
                "schema_id": schema_id,
                "group_name": field.group_name,
                "is_repeating_group": field.is_repeating_group,
                "pole_entity_type": field.pole_entity_type,
                "field_name": field.field_name,
                "data_type": field.data_type,
                "is_required": field.is_required,
                "target_table": field.target_table,
                "target_column": field.target_column,
                "is_identifier": field.is_identifier,
                "identifier_type": field.identifier_type,
                "extraction_hint": field.extraction_hint,
                "display_order": field.display_order,
            },
        )

    for relationship in payload.relationships:
        db.execute(
            text(
                """
                INSERT INTO SchemaRelationship
                (
                    schema_id, from_group, to_group, relationship_type, direction,
                    fixed_edge_properties, edge_property_source_fields
                )
                VALUES
                (
                    :schema_id, :from_group, :to_group, :relationship_type, :direction,
                    :fixed_edge_properties, :edge_property_source_fields
                )
                """
            ),
            {
                "schema_id": schema_id,
                "from_group": relationship.from_group,
                "to_group": relationship.to_group,
                "relationship_type": relationship.relationship_type,
                "direction": relationship.direction,
                "fixed_edge_properties": json.dumps(relationship.fixed_edge_properties or {}),
                "edge_property_source_fields": ",".join(relationship.edge_property_source_fields or []),
            },
        )

    db.commit()
    return {"schema_id": schema_id, "doc_type": doc_type, "version": next_version, "is_active": False}


@router.put("/schema/{doc_type}/activate/{version}")
def activate_schema_version(doc_type: str, version: int, db: Session = Depends(get_db)) -> dict[str, object]:
    doc_type = doc_type.upper()
    target = _get_schema_row(db, doc_type=doc_type, version=version)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Schema {doc_type} v{version} not found.")

    db.execute(text("UPDATE SchemaDefinition SET is_active = false WHERE doc_type = :doc_type"), {"doc_type": doc_type})
    db.execute(
        text("UPDATE SchemaDefinition SET is_active = true WHERE doc_type = :doc_type AND version = :version"),
        {"doc_type": doc_type, "version": version},
    )
    db.commit()
    return {"doc_type": doc_type, "active_version": version}


@router.post("/schema/{doc_type}/rollback/{version}")
def rollback_schema_version(doc_type: str, version: int, db: Session = Depends(get_db)) -> dict[str, object]:
    # Rollback is just re-activating an older version.
    return activate_schema_version(doc_type=doc_type, version=version, db=db)

