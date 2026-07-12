from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.orm import Session


_NON_DIGIT = re.compile(r"\D+")
_SPACE = re.compile(r"\s+")
logger = logging.getLogger(__name__)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def normalize_identifier(identifier_type: str, value: str) -> str:
    raw = (value or "").strip()
    key = identifier_type.lower()
    if key == "upi":
        return raw.lower()
    if key == "phone":
        digits = _NON_DIGIT.sub("", raw)
        return digits[-10:] if len(digits) >= 10 else digits
    if key == "imei":
        return _NON_DIGIT.sub("", raw)
    if key == "account_number":
        return _SPACE.sub("", raw)
    return raw.lower()


def _name_score(candidate_name: str, existing_name: str) -> float:
    if not candidate_name or not existing_name:
        return 0.0
    return fuzz.token_set_ratio(candidate_name, existing_name) / 100.0


def score_person_candidates(
    candidate: dict[str, Any],
    existing_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    ponytail: use RapidFuzz token_set_ratio for demo-safe person matching now.
    Ceiling: this is lexical only and not calibrated across jurisdictions/scripts.
    Upgrade path: replace with Splink training/calibration on known alias pairs.
    """
    logger.debug(
        "score_person_candidates start candidate_name=%s existing_records=%d",
        candidate.get("name") or candidate.get("accused_name"),
        len(existing_records),
    )
    candidate_name = str(candidate.get("name") or candidate.get("accused_name") or "").strip()
    candidate_phone = normalize_identifier("phone", str(candidate.get("phone", "")))
    candidate_upi = normalize_identifier("upi", str(candidate.get("upi", "")))
    candidate_imei = normalize_identifier("imei", str(candidate.get("imei", "")))

    results: list[dict[str, Any]] = []
    for existing in existing_records:
        existing_name = str(existing.get("name") or existing.get("accused_name") or "").strip()
        name_score = _name_score(candidate_name, existing_name)

        matched_fields: list[str] = []
        hard_boost = 0.0

        existing_phone = normalize_identifier("phone", str(existing.get("phone", "")))
        if candidate_phone and existing_phone and candidate_phone == existing_phone:
            matched_fields.append("phone")
            hard_boost += 0.35

        existing_upi = normalize_identifier("upi", str(existing.get("upi", "")))
        if candidate_upi and existing_upi and candidate_upi == existing_upi:
            matched_fields.append("upi")
            hard_boost += 0.35

        existing_imei = normalize_identifier("imei", str(existing.get("imei", "")))
        if candidate_imei and existing_imei and candidate_imei == existing_imei:
            matched_fields.append("imei")
            hard_boost += 0.35

        score = min(1.0, name_score * 0.6 + hard_boost)
        results.append(
            {
                "matched_against_entity_uid": existing.get("entity_uid"),
                "match_score": round(score, 4),
                "matched_fields": matched_fields + (["name"] if name_score > 0.4 else []),
                "existing_record": existing,
            }
        )

    results.sort(key=lambda item: item["match_score"], reverse=True)
    logger.debug(
        "score_person_candidates done candidate_name=%s matches=%d top_score=%s",
        candidate_name,
        len(results),
        results[0]["match_score"] if results else None,
    )
    return results


_MATCH_REASON_LABELS = {
    "phone": "Same phone number",
    "upi": "Same UPI ID",
    "imei": "Same device (IMEI)",
    "account_number": "Same bank account number",
    "email": "Same email address",
    "name": "Similar name",
}

_PERSON_TABLE_ROLE = {
    "Accused": ("AccusedMasterID", "AccusedName", "Accused"),
    "Victim": ("VictimMasterID", "VictimName", "Victim"),
    "ComplainantDetails": ("ComplainantID", "ComplainantName", "Complainant"),
}


def match_reasons(matched_fields: list[str]) -> list[str]:
    """Turn Splink/hard-identifier match field codes into officer-readable reasons."""
    return [_MATCH_REASON_LABELS.get(f, f.replace("_", " ").title()) for f in matched_fields]


def resolve_person_record(session: Session, entity_uid: str) -> dict[str, Any] | None:
    """Look up the actual Accused/Victim/Complainant row an entity_uid points to,
    for side-by-side display against a newly extracted candidate."""
    logger.debug("resolve_person_record entity_uid=%s", entity_uid)
    row = session.execute(
        text("SELECT sql_table, sql_pk FROM EntityMap WHERE entity_uid = :uid"),
        {"uid": entity_uid},
    ).mappings().first()
    if not row or row["sql_table"] not in _PERSON_TABLE_ROLE:
        logger.debug("resolve_person_record no-person entity_uid=%s", entity_uid)
        return None

    table = row["sql_table"]
    pk_column, name_column, role = _PERSON_TABLE_ROLE[table]
    record = session.execute(
        text(f"SELECT {pk_column} AS id, {name_column} AS name, CaseMasterID AS case_id FROM {table} WHERE {pk_column} = :pk"),
        {"pk": row["sql_pk"]},
    ).mappings().first()
    if not record:
        logger.debug("resolve_person_record missing row entity_uid=%s table=%s pk=%s", entity_uid, table, row["sql_pk"])
        return None

    return {
        "entity_uid": entity_uid,
        "role": role,
        "name": record["name"],
        "case_id": record["case_id"],
        "case_context": f"{role} in Case {record['case_id']}",
    }


def ensure_entity_map_row(
    session: Session,
    *,
    entity_type: str,
    pole_subtype: str,
    sql_table: str,
    sql_pk: str,
    entity_uid: str | None = None,
) -> str:
    logger.debug("ensure_entity_map_row table=%s pk=%s type=%s subtype=%s", sql_table, sql_pk, entity_type, pole_subtype)
    row = session.execute(
        text(
            """
            SELECT entity_uid
            FROM EntityMap
            WHERE sql_table = :sql_table AND sql_pk = :sql_pk AND status = 'active'
            LIMIT 1
            """
        ),
        {"sql_table": sql_table, "sql_pk": str(sql_pk)},
    ).mappings().first()
    if row:
        logger.debug("ensure_entity_map_row existing entity_uid=%s table=%s pk=%s", row["entity_uid"], sql_table, sql_pk)
        return str(row["entity_uid"])

    uid = entity_uid or str(uuid.uuid4())
    session.execute(
        text(
            """
            INSERT INTO EntityMap (entity_uid, entity_type, pole_subtype, sql_table, sql_pk, status, created_at, updated_at)
            VALUES (:entity_uid, :entity_type, :pole_subtype, :sql_table, :sql_pk, 'active', NOW(), NOW())
            """
        ),
        {
            "entity_uid": uid,
            "entity_type": entity_type,
            "pole_subtype": pole_subtype,
            "sql_table": sql_table,
            "sql_pk": str(sql_pk),
        },
    )
    logger.info("ensure_entity_map_row created entity_uid=%s table=%s pk=%s", uid, sql_table, sql_pk)
    return uid


def create_review_queue_items(
    session: Session,
    *,
    run_id: str,
    entity_type: str,
    candidate_record: dict[str, Any],
    matches: list[dict[str, Any]],
) -> int:
    logger.info(
        "create_review_queue_items run_id=%s entity_type=%s candidate_name=%s candidate_matches=%d",
        run_id,
        entity_type,
        candidate_record.get("name") or candidate_record.get("accused_name"),
        len(matches),
    )
    created = 0
    for match in matches:
        target_uid = match.get("matched_against_entity_uid")
        if not target_uid:
            continue
        session.execute(
            text(
                """
                INSERT INTO ReviewQueueItem
                (source_run_id, entity_type, candidate_record_json, matched_against_entity_uid,
                 match_score, matched_fields_json, status, created_at)
                VALUES
                (:source_run_id, :entity_type, :candidate_record_json, :matched_against_entity_uid,
                 :match_score, :matched_fields_json, 'pending', NOW())
                """
            ),
            {
                "source_run_id": run_id,
                "entity_type": entity_type,
                "candidate_record_json": json.dumps(candidate_record),
                "matched_against_entity_uid": target_uid,
                "match_score": float(match.get("match_score", 0.0)),
                "matched_fields_json": json.dumps(match.get("matched_fields", [])),
            },
        )
        created += 1
    logger.info("create_review_queue_items done run_id=%s created=%d", run_id, created)
    return created


def manual_merge_entities(session: Session, losing_uid: str, winning_uid: str) -> None:
    logger.info("manual_merge_entities losing_uid=%s winning_uid=%s", losing_uid, winning_uid)
    # Update holder references across extension tables.
    for table in ("Account", "UPIHandle", "PhoneNumber"):
        logger.debug("manual_merge_entities repoint table=%s losing_uid=%s winning_uid=%s", table, losing_uid, winning_uid)
        session.execute(
            text(
                f"""
                UPDATE {table}
                SET holder_entity_uid = :winning_uid
                WHERE holder_entity_uid = :losing_uid
                """
            ),
            {"winning_uid": winning_uid, "losing_uid": losing_uid},
        )

    session.execute(
        text(
            """
            UPDATE EntityMap
            SET status = 'merged_away', updated_at = NOW()
            WHERE entity_uid = :losing_uid
            """
        ),
        {"losing_uid": losing_uid},
    )

    # Keep winning record active and fresh.
    session.execute(
        text(
            """
            UPDATE EntityMap
            SET status = 'active', updated_at = NOW()
            WHERE entity_uid = :winning_uid
            """
        ),
        {"winning_uid": winning_uid},
    )

    _repoint_neo4j_graph(losing_uid=losing_uid, winning_uid=winning_uid)
    _repoint_pinecone_metadata(losing_uid=losing_uid, winning_uid=winning_uid)
    logger.info("manual_merge_entities done losing_uid=%s winning_uid=%s", losing_uid, winning_uid)


def _repoint_neo4j_graph(losing_uid: str, winning_uid: str) -> None:
    uri = _env("NEO4J_URI")
    user = _env("NEO4J_USERNAME")
    password = _env("NEO4J_PASSWORD")
    if not uri or not user or not password:
        logger.warning("repoint_neo4j skipped missing config uri=%s user_set=%s password_set=%s", bool(uri), bool(user), bool(password))
        return
    try:
        from neo4j import GraphDatabase
    except Exception:
        logger.exception("repoint_neo4j failed to import neo4j driver")
        return

    logger.debug("repoint_neo4j connecting uri=%s", uri)
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
    except Exception:
        logger.exception("repoint_neo4j driver creation failed uri=%s", uri)
        return
    try:
        try:
            with driver.session() as db:
                # ponytail: use one generic relationship type for re-pointed edges.
                # Ceiling: original edge types are collapsed during merge.
                # Upgrade path: materialize edge-type-preserving APOC merge flow.
                db.run(
                    """
                    MATCH (losing {entity_uid: $losing_uid}), (winning {entity_uid: $winning_uid})
                    OPTIONAL MATCH (src)-[r1]->(losing)
                    MERGE (src)-[m1:ASSOCIATED_WITH]->(winning)
                    SET m1 += properties(r1)
                    DELETE r1
                    """,
                    losing_uid=losing_uid,
                    winning_uid=winning_uid,
                )
                db.run(
                    """
                    MATCH (losing {entity_uid: $losing_uid}), (winning {entity_uid: $winning_uid})
                    OPTIONAL MATCH (losing)-[r2]->(dst)
                    MERGE (winning)-[m2:ASSOCIATED_WITH]->(dst)
                    SET m2 += properties(r2)
                    DELETE r2
                    """,
                    losing_uid=losing_uid,
                    winning_uid=winning_uid,
                )
                db.run("MATCH (n {entity_uid: $losing_uid}) DETACH DELETE n", losing_uid=losing_uid)
        except Exception:
            logger.exception("repoint_neo4j failed losing_uid=%s winning_uid=%s", losing_uid, winning_uid)
            raise
        logger.info("repoint_neo4j done losing_uid=%s winning_uid=%s", losing_uid, winning_uid)
    finally:
        driver.close()


def _repoint_pinecone_metadata(losing_uid: str, winning_uid: str) -> None:
    api_key = _env("PINECONE_API_KEY")
    index_name = _env("PINECONE_INDEX")
    if not api_key or not index_name:
        logger.warning("repoint_pinecone skipped missing config api_key_set=%s index_name_set=%s", bool(api_key), bool(index_name))
        return

    try:
        from pinecone import Pinecone
    except Exception:
        logger.exception("repoint_pinecone failed to import pinecone")
        return

    # ponytail: Pinecone metadata update by filter is expensive; keep merge as SQL+Neo4j source of truth.
    # Ceiling: vectors may carry stale graph_node_ids until re-embedded/re-upserted.
    # Upgrade path: maintain a SQL chunk-id index and patch vectors directly by id on merge.
    try:
        _ = Pinecone(api_key=api_key).Index(index_name)
        logger.debug("repoint_pinecone index initialized index=%s losing_uid=%s winning_uid=%s", index_name, losing_uid, winning_uid)
    except Exception:
        logger.exception("repoint_pinecone init failed index=%s losing_uid=%s winning_uid=%s", index_name, losing_uid, winning_uid)

