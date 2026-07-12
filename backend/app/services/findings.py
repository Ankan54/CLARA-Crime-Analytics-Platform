"""Builds the officer-facing "what did we find in these documents" view from the
Phase A checkpoint (before Proceed loads it into Postgres/Neo4j/Pinecone).

Case-file language, not storage language: no table names, no entity_uids as the
primary label. The "connections" preview mirrors the real graph builder in
catalyst_functions/ingest_processor/pipeline/processor.py (_build_edges/_owns_edges)
but reads straight from the checkpoint instead of committed DB rows, since Objects
only get their real (deduped) entity_uid once Phase B loads them.

ponytail: object identity is not deduplicated across files in this preview (each
file's Account/UPI/Phone mention gets its own node) — Phase B's real load still
dedups correctly by normalized identifier. Ceiling: a demo case with the same
account in two evidence files shows two preview nodes. Upgrade path: normalize +
dedupe node ids across files here too, same normalize() rules as processor.py.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.orm import Session

from .entity_resolution import match_reasons, resolve_person_record

logger = logging.getLogger(__name__)

_DOC_TYPE_LABELS = {
    "FIR": "First Information Report",
    "IR": "Investigation Report",
    "EVIDENCE_BANK_STATEMENT": "Bank Statement",
    "EVIDENCE_UPI_SCREENSHOT": "UPI Payment Screenshot",
    "EVIDENCE_CHAT_SCREENSHOT": "Chat Screenshot",
}

_GROUP_LABELS = {
    "CaseMaster": "Case",
    "Evidence": "Evidence file",
    "Accused": "Accused",
    "Victim": "Victim",
    "ComplainantDetails": "Complainant",
    "BankStatement": "Bank Account",
    "UPIPayer": "UPI Handle",
    "UPIPayee": "UPI Handle",
    "MentionedAccount": "Bank Account",
    "MentionedUPI": "UPI Handle",
    "MentionedPhone": "Phone Number",
    "MentionedDevice": "Device",
    "ChatParticipant": "Phone Number",
    "InvestigationReport": "Investigation Report",
}

_RELATIONSHIP_PHRASES = {
    "INVOLVES": "is involved in the case",
    "MENTIONS": "is mentioned in",
    "HAS_EVIDENCE": "has evidence file",
    "OWNS": "owns",
}


def _doc_type_label(doc_type: str) -> str:
    return _DOC_TYPE_LABELS.get(doc_type, doc_type.replace("EVIDENCE_", "").replace("_", " ").title())


def _group_label(group_name: str) -> str:
    return _GROUP_LABELS.get(group_name, group_name.replace("_", " "))


def _pluralize(label: str, count: int) -> str:
    if count == 1:
        return label
    return label + "es" if label.endswith(("ch", "sh", "s")) else label + "s"


def _display_name(fields: dict[str, Any]) -> str | None:
    for key, value in fields.items():
        if value and "name" in key.lower():
            return str(value)
    return None


def _node_label(group_name: str, fields: dict[str, Any]) -> str:
    name = _display_name(fields)
    if name:
        return name
    for key in ("account_number", "vpa", "number", "imei", "phone_number", "payer_vpa", "payee_vpa"):
        if fields.get(key):
            return str(fields[key])
    return _group_label(group_name)


def _non_empty_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if any(v for v in (r.get("fields") or {}).values())]


def _file_summary(doc_type: str, groups: dict[str, list[dict[str, Any]]]) -> str:
    parts: list[str] = []
    for group_name, rows in groups.items():
        if group_name in ("CaseMaster", "Evidence", "ActSection") or not rows:
            continue
        non_empty = _non_empty_rows(rows)
        if non_empty:
            label = _group_label(group_name).lower()
            parts.append(f"{len(non_empty)} {_pluralize(label, len(non_empty))}")
    if not parts:
        return f"No structured details could be extracted from this {_doc_type_label(doc_type).lower()}."
    return "Found " + ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Schema info (pole_entity_type per group, relationship rows) for the preview graph
# ---------------------------------------------------------------------------


def _schema_info(db: Session, schema_ids: set[int]) -> tuple[dict[int, dict[str, str | None]], dict[int, list[dict[str, Any]]]]:
    if not schema_ids:
        logger.debug("findings schema_info: no schema ids")
        return {}, {}
    ids = list(schema_ids)
    logger.debug("findings schema_info start schema_ids=%s", sorted(ids))

    try:
        field_rows = db.execute(
            text("SELECT DISTINCT schema_id, group_name, pole_entity_type FROM SchemaField WHERE schema_id = ANY(:ids)"),
            {"ids": ids},
        ).mappings().all()
    except Exception:
        logger.exception("findings schema_info failed while reading SchemaField")
        raise
    pole_types: dict[int, dict[str, str | None]] = {}
    for row in field_rows:
        pole_types.setdefault(int(row["schema_id"]), {})[row["group_name"]] = row["pole_entity_type"]

    try:
        rel_rows = db.execute(
            text(
                """
                SELECT schema_id, from_group, to_group, relationship_type, fixed_edge_properties
                FROM SchemaRelationship WHERE schema_id = ANY(:ids)
                """
            ),
            {"ids": ids},
        ).mappings().all()
    except Exception:
        logger.exception("findings schema_info failed while reading SchemaRelationship")
        raise
    relationships: dict[int, list[dict[str, Any]]] = {}
    for row in rel_rows:
        relationships.setdefault(int(row["schema_id"]), []).append(dict(row))
    logger.debug(
        "findings schema_info done schema_count=%d field_rows=%d relationship_rows=%d",
        len(ids),
        len(field_rows),
        len(rel_rows),
    )
    return pole_types, relationships


# ---------------------------------------------------------------------------
# Per-file connections preview (nodes + edges)
# ---------------------------------------------------------------------------


def _owns_edges(person_ids: list[str], object_ids: list[str], nodes: dict[str, dict[str, Any]], phrase: str) -> list[dict[str, Any]]:
    edges = []
    for obj_id in object_ids:
        if len(person_ids) == 1:
            edges.append({"from": person_ids[0], "to": obj_id, "label": phrase})
            continue
        best_id, best_score = None, 0.0
        obj_label = nodes[obj_id]["label"]
        for person_id in person_ids:
            score = fuzz.token_set_ratio(obj_label, nodes[person_id]["label"]) / 100.0
            if score > best_score:
                best_score, best_id = score, person_id
        if best_id and best_score >= 0.72:
            edges.append({"from": best_id, "to": obj_id, "label": phrase})
    return edges


def _transaction_edges(
    groups: dict[str, list[dict[str, Any]]], group_node_ids: dict[str, list[str]], nodes: dict[str, dict[str, Any]], filename: str
) -> list[dict[str, Any]]:
    rows = groups.get("Transaction") or []
    if not rows:
        return []
    self_id = (group_node_ids.get("BankStatement") or [None])[0]
    payer_id = (group_node_ids.get("UPIPayer") or [None])[0]
    payee_id = (group_node_ids.get("UPIPayee") or [None])[0]

    edges: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        fields = row["fields"]
        amount = fields.get("amount")
        if amount is None:
            continue
        direction = str(fields.get("direction") or "").lower()
        counterparty_label = fields.get("counterparty_name") or fields.get("counterparty_account") or fields.get("counterparty_upi")

        from_id = to_id = None
        if self_id and counterparty_label:
            cp_id = f"{filename}::Transaction#{idx}::counterparty"
            nodes.setdefault(cp_id, {"id": cp_id, "label": str(counterparty_label), "kind": "Counterparty", "file": filename})
            if direction in ("debit", "dr", "out"):
                from_id, to_id = self_id, cp_id
            else:
                from_id, to_id = cp_id, self_id
        elif payer_id and payee_id:
            from_id, to_id = payer_id, payee_id
        else:
            continue

        label = f"paid Rs.{amount:,.0f}" if isinstance(amount, (int, float)) else f"paid {amount}"
        edges.append({"from": from_id, "to": to_id, "label": label, "amount": amount, "date": fields.get("txn_timestamp")})
    return edges


def _build_file_graph(
    file_entry: dict[str, Any], pole_types: dict[str, str | None], relationships: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups = file_entry.get("groups") or {}
    provisional_uids = file_entry.get("provisional_uids") or {}
    filename = file_entry["filename"]

    nodes: dict[str, dict[str, Any]] = {}
    group_node_ids: dict[str, list[str]] = {}

    case_fields = (groups.get("CaseMaster") or [{"fields": {}}])[0].get("fields") or {}
    case_node_id = f"{filename}::CaseMaster#0"
    nodes[case_node_id] = {"id": case_node_id, "label": case_fields.get("case_no") or "This Case", "kind": "Case", "file": filename}
    group_node_ids["CaseMaster"] = [case_node_id]

    if str(file_entry.get("doc_type", "")).startswith("EVIDENCE"):
        evidence_node_id = f"{filename}::Evidence#0"
        nodes[evidence_node_id] = {"id": evidence_node_id, "label": filename, "kind": "Evidence file", "file": filename}
        group_node_ids["Evidence"] = [evidence_node_id]

    for group_name, rows in groups.items():
        if group_name in ("CaseMaster", "Transaction", "ActSection"):
            continue
        if not pole_types.get(group_name):
            continue
        ids = []
        for idx, row in enumerate(rows):
            fields = row.get("fields") or {}
            if not any(v for v in fields.values()):
                continue
            node_id = provisional_uids.get(f"{group_name}#{idx}") or f"{filename}::{group_name}#{idx}"
            nodes[node_id] = {"id": node_id, "label": _node_label(group_name, fields), "kind": _group_label(group_name), "file": filename}
            ids.append(node_id)
        if ids:
            group_node_ids[group_name] = ids

    edges: list[dict[str, Any]] = []
    for rel in relationships:
        if rel["relationship_type"] == "TRANSACTED_WITH":
            continue
        from_ids = group_node_ids.get(rel["from_group"]) or []
        to_ids = group_node_ids.get(rel["to_group"]) or []
        if not from_ids or not to_ids:
            continue

        fixed_props = rel.get("fixed_edge_properties") or {}
        if isinstance(fixed_props, str):
            fixed_props = json.loads(fixed_props or "{}")
        role = fixed_props.get("role")
        phrase = f"is involved as {role}" if role else _RELATIONSHIP_PHRASES.get(rel["relationship_type"], rel["relationship_type"].replace("_", " ").lower())

        if rel["relationship_type"] == "OWNS":
            edges.extend(_owns_edges(from_ids, to_ids, nodes, phrase))
            continue
        for from_id in from_ids:
            for to_id in to_ids:
                edges.append({"from": from_id, "to": to_id, "label": phrase})

    edges.extend(_transaction_edges(groups, group_node_ids, nodes, filename))
    return list(nodes.values()), edges


# ---------------------------------------------------------------------------
# Entities + transactions summaries (flat lists for the review screen)
# ---------------------------------------------------------------------------

_PERSON_GROUPS = {"Accused": "Accused", "Victim": "Victim", "ComplainantDetails": "Complainant"}


def _aggregate_entities(files: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    people: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []
    upis: list[dict[str, Any]] = []
    phones: list[dict[str, Any]] = []
    devices: list[dict[str, Any]] = []

    for file_entry in files:
        groups = file_entry.get("groups") or {}
        filename = file_entry["filename"]

        for group_name, role in _PERSON_GROUPS.items():
            for row in _non_empty_rows(groups.get(group_name) or []):
                fields = row["fields"]
                name = _display_name(fields)
                if name:
                    people.append({"name": name, "role": role, "file": filename})

        for group_name in ("BankStatement", "MentionedAccount"):
            for row in _non_empty_rows(groups.get(group_name) or []):
                fields = row["fields"]
                account_number = fields.get("account_number")
                if account_number:
                    accounts.append(
                        {
                            "account_number": account_number,
                            "bank_name": fields.get("bank_name"),
                            "holder_name": fields.get("account_holder_name"),
                            "file": filename,
                        }
                    )

        for group_name, vpa_key, name_key in (
            ("UPIPayer", "payer_vpa", "payer_name"),
            ("UPIPayee", "payee_vpa", "payee_name"),
            ("MentionedUPI", "vpa", None),
        ):
            for row in _non_empty_rows(groups.get(group_name) or []):
                fields = row["fields"]
                vpa = fields.get(vpa_key)
                if vpa:
                    upis.append({"vpa": vpa, "holder_name": fields.get(name_key) if name_key else None, "file": filename})

        for group_name, number_key in (("ChatParticipant", "phone_number"), ("MentionedPhone", "number")):
            for row in _non_empty_rows(groups.get(group_name) or []):
                fields = row["fields"]
                number = fields.get(number_key)
                if number:
                    phones.append({"number": number, "holder_name": fields.get("display_name"), "file": filename})

        for row in _non_empty_rows(groups.get("MentionedDevice") or []):
            fields = row["fields"]
            imei = fields.get("imei")
            if imei:
                devices.append({"imei": imei, "file": filename})

    return {"people": people, "bank_accounts": accounts, "upi_handles": upis, "phone_numbers": phones, "devices": devices}


def _transactions_for_file(file_entry: dict[str, Any]) -> list[dict[str, Any]]:
    groups = file_entry.get("groups") or {}
    txn_rows = groups.get("Transaction") or []
    if not txn_rows:
        return []

    self_account = (groups.get("BankStatement") or [None])[0]
    payer = (groups.get("UPIPayer") or [None])[0]
    payee = (groups.get("UPIPayee") or [None])[0]
    self_label = None
    if self_account:
        f = self_account["fields"]
        self_label = f.get("account_holder_name") or f.get("account_number") or "This account"

    out = []
    for row in txn_rows:
        fields = row["fields"]
        amount = fields.get("amount")
        if amount is None:
            continue
        direction = str(fields.get("direction") or "").lower()
        counterparty = fields.get("counterparty_name") or fields.get("counterparty_account") or fields.get("counterparty_upi")

        if self_account and counterparty:
            from_label, to_label = (self_label, counterparty) if direction in ("debit", "dr", "out") else (counterparty, self_label)
        elif payer and payee:
            pf, qf = payer["fields"], payee["fields"]
            from_label = pf.get("payer_name") or pf.get("payer_vpa") or "Payer"
            to_label = qf.get("payee_name") or qf.get("payee_vpa") or "Payee"
        else:
            continue

        out.append(
            {
                "from": from_label,
                "to": to_label,
                "amount": amount,
                "date": fields.get("txn_timestamp"),
                "reference": fields.get("utr_ref"),
                "mode": fields.get("mode"),
                "file": file_entry["filename"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Potential matches (pending review items for this run)
# ---------------------------------------------------------------------------


def _potential_matches(db: Session, run_id: str) -> list[dict[str, Any]]:
    logger.debug("findings potential_matches start run_id=%s", run_id)
    try:
        rows = db.execute(
            text(
                """
                SELECT review_id, candidate_record_json, matched_against_entity_uid, match_score, matched_fields_json, status
                FROM ReviewQueueItem
                WHERE source_run_id = :run_id
                ORDER BY created_at ASC
                """
            ),
            {"run_id": run_id},
        ).mappings().all()
    except Exception:
        logger.exception("findings potential_matches query failed run_id=%s", run_id)
        raise

    out = []
    for row in rows:
        candidate = row["candidate_record_json"]
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate or "{}")
            except json.JSONDecodeError:
                logger.warning("findings potential_matches candidate JSON decode failed review_id=%s", row["review_id"], exc_info=True)
                candidate = {}
        matched_fields = row["matched_fields_json"]
        if isinstance(matched_fields, str):
            try:
                matched_fields = json.loads(matched_fields or "[]")
            except json.JSONDecodeError:
                logger.warning("findings potential_matches matched_fields JSON decode failed review_id=%s", row["review_id"], exc_info=True)
                matched_fields = []
        existing = resolve_person_record(db, str(row["matched_against_entity_uid"])) if row["matched_against_entity_uid"] else None

        out.append(
            {
                "review_id": row["review_id"],
                "status": row["status"],
                "candidate_name": candidate.get("name"),
                "existing_record": existing,
                "match_score": float(row["match_score"]),
                "match_reasons": match_reasons(matched_fields),
            }
        )
    logger.debug("findings potential_matches done run_id=%s count=%d", run_id, len(out))
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_findings(db: Session, run: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    run_id = run.get("run_id")
    logger.info("build_findings start run_id=%s case_id=%s", run_id, run.get("case_id"))
    try:
        files: list[dict[str, Any]] = manifest.get("files") or []
        schema_ids = {int(f["schema_id"]) for f in files if f.get("schema_id") is not None}
        pole_types_by_schema, relationships_by_schema = _schema_info(db, schema_ids)

        file_summaries = []
        all_nodes: list[dict[str, Any]] = []
        all_edges: list[dict[str, Any]] = []
        all_transactions: list[dict[str, Any]] = []

        for file_entry in files:
            doc_type = file_entry.get("doc_type", "")
            groups = file_entry.get("groups") or {}
            file_summaries.append(
                {
                    "filename": file_entry.get("filename"),
                    "file_type": file_entry.get("file_type"),
                    "doc_type": doc_type,
                    "doc_type_label": _doc_type_label(doc_type),
                    "summary": _file_summary(doc_type, groups),
                }
            )

            schema_id = int(file_entry["schema_id"]) if file_entry.get("schema_id") is not None else None
            nodes, edges = _build_file_graph(
                file_entry,
                pole_types_by_schema.get(schema_id, {}),
                relationships_by_schema.get(schema_id, []),
            )
            all_nodes.extend(nodes)
            all_edges.extend(edges)
            all_transactions.extend(_transactions_for_file(file_entry))

        entities = _aggregate_entities(files)
        potential_matches = _potential_matches(db, run["run_id"])

        counts = {
            "people": len(entities["people"]),
            "bank_accounts": len(entities["bank_accounts"]),
            "upi_handles": len(entities["upi_handles"]),
            "phone_numbers": len(entities["phone_numbers"]),
            "devices": len(entities["devices"]),
            "transactions": len(all_transactions),
            "potential_matches": len([m for m in potential_matches if m["status"] == "pending"]),
        }

        logger.info(
            "build_findings done run_id=%s files=%d people=%d accounts=%d txns=%d pending_matches=%d",
            run_id,
            len(files),
            counts["people"],
            counts["bank_accounts"],
            counts["transactions"],
            counts["potential_matches"],
        )
        return {
            "run_id": run["run_id"],
            "case_id": run["case_id"],
            "files": file_summaries,
            "entities": entities,
            "transactions": all_transactions,
            "connections": {"nodes": all_nodes, "edges": all_edges},
            "potential_matches": potential_matches,
            "counts": counts,
        }
    except Exception:
        logger.exception("build_findings failed run_id=%s", run_id)
        raise
