from __future__ import annotations

import json
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import SchemaVersionCreateRequest


router = APIRouter(prefix="/api/v1/admin", tags=["schema-admin"])


def _dominant_target_table(tables: list[str]) -> str | None:
    """Most common non-empty target_table for a group; None if none."""
    counts = Counter(t for t in tables if t)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _canonicalize_group(
    group: str,
    *,
    relationship_type: str,
    group_targets: dict[str, str | None],
) -> str:
    # Live Neo4j stores Account-[:TRANSACTED_WITH]->Account, not Transaction nodes.
    if relationship_type == "TRANSACTED_WITH" and group == "Transaction":
        return "Account"
    target = group_targets.get(group)
    return target or group


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
            ORDER BY
              CASE doc_type
                WHEN 'FIR' THEN 0
                WHEN 'IR' THEN 1
                ELSE 2
              END,
              doc_type
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/ontology")
def get_schema_ontology(db: Session = Depends(get_db)) -> dict[str, object]:
    """Union active SchemaRelationship rows into a canonical entity-type ontology."""
    active = db.execute(
        text(
            """
            SELECT schema_id, doc_type
            FROM SchemaDefinition
            WHERE is_active = true
            """
        )
    ).mappings().all()
    if not active:
        return {"title": "Crime intelligence model", "entities": [], "relationships": []}

    schema_ids = [int(row["schema_id"]) for row in active]
    doc_by_schema = {int(row["schema_id"]): str(row["doc_type"]) for row in active}

    fields = db.execute(
        text(
            """
            SELECT schema_id, group_name, pole_entity_type, field_name, target_table,
                   is_identifier, display_order, field_id
            FROM SchemaField
            WHERE schema_id = ANY(:ids)
            ORDER BY group_name, COALESCE(display_order, 0), field_id
            """
        ),
        {"ids": schema_ids},
    ).mappings().all()

    rels = db.execute(
        text(
            """
            SELECT schema_id, from_group, to_group, relationship_type
            FROM SchemaRelationship
            WHERE schema_id = ANY(:ids)
            ORDER BY relationship_id
            """
        ),
        {"ids": schema_ids},
    ).mappings().all()

    # group_name -> list of target_tables / poles / candidate key fields
    tables_by_group: dict[str, list[str]] = defaultdict(list)
    poles_by_group: dict[str, list[str]] = defaultdict(list)
    # (group, field_name) ordered candidates: identifiers first, then first field
    id_fields_by_group: dict[str, list[str]] = defaultdict(list)
    first_fields_by_group: dict[str, list[str]] = defaultdict(list)

    for row in fields:
        group = str(row["group_name"])
        if row["target_table"]:
            tables_by_group[group].append(str(row["target_table"]))
        if row["pole_entity_type"]:
            poles_by_group[group].append(str(row["pole_entity_type"]))
        fname = str(row["field_name"])
        if fname not in first_fields_by_group[group]:
            first_fields_by_group[group].append(fname)
        if row["is_identifier"] and fname not in id_fields_by_group[group]:
            id_fields_by_group[group].append(fname)

    group_targets = {
        group: _dominant_target_table(tables) for group, tables in tables_by_group.items()
    }
    # Structural groups that appear only in relationships (Evidence) have no fields.
    for row in rels:
        for group in (str(row["from_group"]), str(row["to_group"])):
            group_targets.setdefault(group, None)

    entities: dict[str, dict[str, object]] = {}
    edge_map: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    def _ensure_entity(entity_id: str, source_group: str, doc_type: str) -> None:
        entry = entities.get(entity_id)
        if entry is None:
            poles = poles_by_group.get(source_group) or []
            pole = Counter(poles).most_common(1)[0][0] if poles else None
            key = None
            for fname in id_fields_by_group.get(source_group, []):
                key = fname
                break
            if key is None:
                for fname in first_fields_by_group.get(source_group, []):
                    key = fname
                    break
            # Prefer Account key when Transaction remapped
            if entity_id == "Account" and key is None:
                for g in ("MentionedAccount", "BankStatement", "Account"):
                    for fname in id_fields_by_group.get(g, []) or first_fields_by_group.get(g, []):
                        key = fname
                        break
                    if key:
                        break
            entry = {
                "id": entity_id,
                "label": entity_id,
                "keyProperty": key,
                "pole": pole,
                "sources": set(),
            }
            entities[entity_id] = entry
        sources = entry["sources"]
        assert isinstance(sources, set)
        sources.add(doc_type)
        # Upgrade key/pole if we learn better metadata from another group
        if entry.get("keyProperty") is None:
            for fname in id_fields_by_group.get(source_group, []) or first_fields_by_group.get(
                source_group, []
            ):
                entry["keyProperty"] = fname
                break
        if entry.get("pole") is None and poles_by_group.get(source_group):
            entry["pole"] = Counter(poles_by_group[source_group]).most_common(1)[0][0]

    for row in rels:
        doc_type = doc_by_schema[int(row["schema_id"])]
        rel_type = str(row["relationship_type"])
        from_group = str(row["from_group"])
        to_group = str(row["to_group"])
        from_id = _canonicalize_group(
            from_group, relationship_type=rel_type, group_targets=group_targets
        )
        to_id = _canonicalize_group(
            to_group, relationship_type=rel_type, group_targets=group_targets
        )
        _ensure_entity(from_id, from_group, doc_type)
        _ensure_entity(to_id, to_group, doc_type)
        edge_map[(from_id, to_id, rel_type)].add(doc_type)

    entity_list = []
    for entity_id in sorted(entities.keys()):
        e = entities[entity_id]
        sources = sorted(e["sources"])  # type: ignore[arg-type]
        entity_list.append(
            {
                "id": e["id"],
                "label": e["label"],
                "keyProperty": e.get("keyProperty"),
                "pole": e.get("pole"),
                "sources": sources,
            }
        )

    relationships = []
    for (frm, to, rel_type), sources in sorted(edge_map.items()):
        relationships.append(
            {
                "id": f"{frm}-{rel_type}-{to}",
                "from": frm,
                "to": to,
                "type": rel_type,
                "sources": sorted(sources),
            }
        )

    return {
        "title": "Crime intelligence model",
        "entities": entity_list,
        "relationships": relationships,
    }


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

