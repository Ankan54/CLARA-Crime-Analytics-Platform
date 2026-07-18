"""
load_neo4j_from_pg.py — Load Neo4j from the already-migrated Postgres historical
data (run migrate_sqlite_to_pg.py first), entity_uid-keyed to match live
ingestion's node identity scheme exactly (see
catalyst_functions/ingest_processor/pipeline/processor.py::_load_graph).

This replaces data_generation/graph_builder.py's CSV+import.cypher approach for
populating the live Neo4j instance: that script keys nodes by natural
identifier (node_id = AccountNo/IMEI/VPA/...), which can never MERGE with
live ingestion's entity_uid-keyed nodes for the same real-world object, and its
generated import.cypher only loads node files, never any rels_*.csv -- and
uses LOAD CSV FROM 'file:///...', which Neo4j Aura (hosted) doesn't support for
local files at all. This script reads FROM Postgres over the Bolt driver
instead, using the exact same MERGE-on-property-only-then-SET-label pattern
_load_graph uses (see the comment there for why: a label in the MERGE pattern
requires an exact label+property match to reuse a node, and the same object
legitimately gets multiple labels over its lifetime).

Idempotent: wipes its own origin='historical' scope before rewriting each run.

Usage:
    python backend/migrations/load_neo4j_from_pg.py
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from neo4j import GraphDatabase
from psycopg.rows import dict_row

from migrate_sqlite_to_pg import SQLITE_PATH_DEFAULT, _build_conninfo, _norm_account, _norm_imei, _norm_phone, _norm_upi

ROOT = Path(__file__).resolve().parents[2]

BATCH_SIZE = 500


def _pg_connect(db_name: str) -> psycopg.Connection:
    return psycopg.connect(_build_conninfo(db_name), row_factory=dict_row, prepare_threshold=None)


def _entity_map(pg: psycopg.Connection) -> dict[tuple[str, str], str]:
    # entity_uid comes back from psycopg as uuid.UUID (Postgres uuid column
    # type) -- Neo4j's Bolt driver can't serialize that, only plain strings.
    with pg.cursor() as cur:
        cur.execute("SELECT sql_table, sql_pk, entity_uid FROM EntityMap WHERE status = 'active'")
        return {(row["sql_table"], row["sql_pk"]): str(row["entity_uid"]) for row in cur.fetchall()}


def _batched(rows: list[dict[str, Any]], size: int = BATCH_SIZE):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _merge_nodes(session, label: str, rows: list[dict[str, Any]], props: tuple[str, ...] = ()) -> int:
    """rows: [{"uid": ..., "case_id": ..., "display_name": ..., <props>: ...}, ...]"""
    if not rows:
        return 0
    set_props = "".join(f", n.{p} = row.{p}" for p in props)
    count = 0
    for batch in _batched(rows):
        session.run(
            f"""
            UNWIND $rows AS row
            MERGE (n {{entity_uid: row.uid}})
            SET n:{label},
                n.origin = 'historical', n.case_id = row.case_id, n.updated_at = datetime(),
                n.display_name = coalesce(row.display_name, n.display_name){set_props}
            """,
            rows=batch,
        )
        count += len(batch)
    return count


def _merge_edges(
    session,
    rel_type: str,
    rows: list[dict[str, Any]],
    merge_key: str | None = None,
    props: tuple[str, ...] = (),
) -> int:
    """rows: [{"from_uid": ..., "to_uid": ..., <merge_key>: ..., <props>: ...}, ...]

    merge_key: property included in the MERGE pattern, so distinct edges between the
    same pair of nodes stay distinct. Without it, MERGE (a)-[r:T]->(b) collapses every
    edge between a and b into one -- fine for MENTIONS/OWNS (which are set-like), but
    wrong for TRANSACTED_WITH, where two accounts legitimately transact many times and
    each transfer is its own edge with its own amount/timestamp.
    """
    if not rows:
        return 0
    key_pattern = f" {{{merge_key}: row.{merge_key}}}" if merge_key else ""
    set_props = "".join(f", r.{p} = row.{p}" for p in props)
    count = 0
    for batch in _batched(rows):
        session.run(
            f"""
            UNWIND $rows AS row
            MATCH (a {{entity_uid: row.from_uid}}), (b {{entity_uid: row.to_uid}})
            MERGE (a)-[r:{rel_type}{key_pattern}]->(b)
            SET r.origin = 'historical'{set_props}
            """,
            rows=batch,
        )
        count += len(batch)
    return count


def _wipe_historical(session) -> int:
    result = session.run("MATCH (n {origin: 'historical'}) DETACH DELETE n RETURN count(n) AS c")
    return result.single()["c"]


def load(pg_db: str = None) -> None:
    load_dotenv(ROOT / ".env")
    pg_db = pg_db or os.getenv("DB_NAME", "postgres")

    pg = _pg_connect(pg_db)
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ.get("NEO4J_USERNAME", "neo4j"), os.environ["NEO4J_PASSWORD"]),
    )

    entity_map = _entity_map(pg)
    print(f"[neo4j-load] EntityMap: {len(entity_map)} entries")

    with driver.session() as session:
        wiped = _wipe_historical(session)
        print(f"[neo4j-load] Wiped {wiped} pre-existing origin='historical' nodes")

        # -- Nodes --------------------------------------------------------
        # CaseMaster/Accused/Victim/ComplainantDetails are exclusively either
        # historical (loaded by migrate_sqlite_to_pg.py) or live (loaded by a
        # PipelineRun) -- never both, unlike Account/UPIHandle/Device/
        # PhoneNumber which are genuinely shared. Confirmed live: re-running
        # this loader after uploading scenario 1's live FIR pulled in live case
        # 1000063 too (SELECT ... FROM CaseMaster has no origin column to filter
        # on) and re-tagged it origin='historical', clobbering the live
        # pipeline's own 'demo' tag. Every live case has exactly one PipelineRun
        # row keyed by case_id; historical cases never do -- use that as the
        # exclusion filter.
        with pg.cursor() as cur:
            cur.execute("SELECT DISTINCT case_id FROM PipelineRun WHERE case_id IS NOT NULL")
            live_case_ids = {row["case_id"] for row in cur.fetchall()}

        with pg.cursor() as cur:
            cur.execute("SELECT CaseMasterID, CrimeNo FROM CaseMaster")
            case_rows = [r for r in cur.fetchall() if r["casemasterid"] not in live_case_ids]
        case_nodes = []
        for row in case_rows:
            uid = entity_map.get(("CaseMaster", str(row["casemasterid"])))
            if uid:
                case_nodes.append({"uid": uid, "case_id": row["casemasterid"], "display_name": row["crimeno"]})
        n = _merge_nodes(session, "CaseMaster", case_nodes)
        print(f"[neo4j-load] OK  CaseMaster nodes: {n}")

        person_specs = [
            ("Accused", "AccusedMasterID", "AccusedName", "Accused"),
            ("Victim", "VictimMasterID", "VictimName", "Victim"),
            ("ComplainantDetails", "ComplainantID", "ComplainantName", "ComplainantDetails"),
        ]
        for table, pk_col, name_col, label in person_specs:
            with pg.cursor() as cur:
                cur.execute(f"SELECT {pk_col}, CaseMasterID, {name_col} FROM {table}")
                rows = [r for r in cur.fetchall() if r["casemasterid"] not in live_case_ids]
            nodes = []
            for row in rows:
                uid = entity_map.get((table, str(row[pk_col.lower()])))
                if uid:
                    nodes.append({
                        "uid": uid,
                        "case_id": row["casemasterid"],
                        "display_name": row[name_col.lower()],
                    })
            n = _merge_nodes(session, label, nodes)
            print(f"[neo4j-load] OK  {label} nodes: {n}")

        # Account/UPIHandle/Device/PhoneNumber ARE genuinely shared between
        # historical and live (that's the whole point -- AGG_ACC_01 etc.), so
        # unlike CaseMaster this isn't a clean origin split. But an object that
        # only exists because of a live upload (e.g. a scenario's controller
        # UPI/IMEI, which identifier_pool.py explicitly requires stay absent
        # from historical data) shouldn't be swept in just because it now
        # exists as a Postgres row -- confirmed live this loader was about to
        # tag a live-only controller UPI/IMEI origin='historical'.
        # source_evidence_id can't distinguish this (migrate_sqlite_to_pg.py's
        # historical Account/UPI/Device/Phone inserts leave it NULL), so use
        # the sqlite seed itself as ground truth: an object counts as
        # historical only if its normalized value actually appears in
        # EXT_Account/EXT_UPI/EXT_Device/EXT_Phone.
        sqlite_conn = sqlite3.connect(SQLITE_PATH_DEFAULT)
        sqlite_conn.row_factory = sqlite3.Row
        historical_normalized: dict[str, set[str]] = {
            "Account": {_norm_account(r["AccountNo"]) for r in sqlite_conn.execute("SELECT AccountNo FROM EXT_Account")},
            "UPIHandle": {_norm_upi(r["VPA"]) for r in sqlite_conn.execute("SELECT VPA FROM EXT_UPI")},
            "Device": {_norm_imei(r["IMEI"]) for r in sqlite_conn.execute("SELECT IMEI FROM EXT_Device")},
            "PhoneNumber": {_norm_phone(r["Number"]) for r in sqlite_conn.execute("SELECT Number FROM EXT_Phone")},
        }
        sqlite_conn.close()
        object_norm_fn = {"Account": _norm_account, "UPIHandle": _norm_upi, "Device": _norm_imei, "PhoneNumber": _norm_phone}

        object_specs = [
            ("Account", "account_id", "account_number_raw", "linked_case_id"),
            ("UPIHandle", "upi_id", "vpa_raw", None),
            ("Device", "device_id", "imei_raw", None),
            ("PhoneNumber", "phone_id", "number_raw", None),
        ]
        object_entity_uid_by_pk: dict[str, dict[int, str]] = {}
        for table, pk_col, name_col, case_col in object_specs:
            case_select = f", {case_col}" if case_col else ""
            with pg.cursor() as cur:
                cur.execute(f"SELECT {pk_col}, {name_col}{case_select} FROM {table}")
                rows = [r for r in cur.fetchall() if object_norm_fn[table](r[name_col]) in historical_normalized[table]]
            nodes = []
            pk_to_uid: dict[int, str] = {}
            for row in rows:
                uid = entity_map.get((table, str(row[pk_col])))
                if not uid:
                    continue
                pk_to_uid[row[pk_col]] = uid
                nodes.append({
                    "uid": uid,
                    "case_id": row.get(case_col.lower()) if case_col else None,
                    "display_name": row[name_col],
                })
            object_entity_uid_by_pk[table] = pk_to_uid
            n = _merge_nodes(session, table, nodes)
            print(f"[neo4j-load] OK  {table} nodes: {n}")

        # IP/Wallet live only as EXT_ rows keyed by their natural text PK (there's no
        # first-class table to resolve/dedupe them into, and live ingestion doesn't
        # produce them). EntityMap rows are minted for them by migrate_sqlite_to_pg.py.
        # Geo/chain properties ride on the node itself -- scenario 4 needs
        # IP.geo_city/lat/long for operator co-location, scenario 3 needs Wallet.chain
        # to label the crypto endpoint.
        ext_object_specs = [
            ("EXT_IP", "IPAddress", "IP", ("IPID", "GeoLat", "GeoLong", "GeoCity")),
            ("EXT_Wallet", "Address", "Wallet", ("WalletID", "Chain")),
        ]
        ext_uid_by_key: dict[str, dict[str, str]] = {}
        for ext_table, pk_col, label, extra_cols in ext_object_specs:
            with pg.cursor() as cur:
                cur.execute(f"SELECT {pk_col}, {', '.join(extra_cols)} FROM {ext_table}")
                rows = cur.fetchall()
            nodes = []
            key_to_uid: dict[str, str] = {}
            for row in rows:
                key = str(row[pk_col.lower()])
                uid = entity_map.get((ext_table, key))
                if not uid:
                    continue
                key_to_uid[key] = uid
                node = {"uid": uid, "case_id": None, "display_name": key}
                node.update({c.lower(): row[c.lower()] for c in extra_cols})
                nodes.append(node)
            ext_uid_by_key[ext_table] = key_to_uid
            n = _merge_nodes(session, label, nodes, props=tuple(c.lower() for c in extra_cols))
            print(f"[neo4j-load] OK  {label} nodes: {n}")

        # Evidence (the generic FIR/mentions provenance row) is deliberately NOT
        # a graph node -- confirmed live (by uploading scenario 1's live FIR)
        # that MENTIONS goes directly CaseMaster->Account/UPIHandle/Device/
        # PhoneNumber, no Evidence intermediary. InvestigationReport IS a real
        # graph node though -- confirmed live (by then also uploading scenario
        # 1's live IR) that live ingestion creates an InvestigationReport node
        # with a direct CaseMaster-[:HAS_EVIDENCE]->InvestigationReport edge (no
        # generic Evidence node there either). An earlier pass here dropped
        # InvestigationReport too, based on FIR-only testing before any IR had
        # ever been uploaded -- fixed once the fuller live shape was visible.
        with pg.cursor() as cur:
            cur.execute("SELECT report_id, case_id, report_date FROM InvestigationReport")
            ir_rows = cur.fetchall()
        ir_nodes = []
        for row in ir_rows:
            if row["case_id"] in live_case_ids:
                continue
            uid = entity_map.get(("InvestigationReport", str(row["report_id"])))
            if uid:
                ir_nodes.append({
                    "uid": uid,
                    "case_id": row["case_id"],
                    "display_name": f"Investigation Report ({row['report_date']})" if row["report_date"] else "Investigation Report",
                })
        n = _merge_nodes(session, "InvestigationReport", ir_nodes)
        print(f"[neo4j-load] OK  InvestigationReport nodes: {n}")

        # -- Relationships --------------------------------------------------
        case_uid_by_id = {c["case_id"]: c["uid"] for c in case_nodes}

        has_evidence_edges = [
            {"from_uid": case_uid_by_id[row["case_id"]], "to_uid": entity_map[("InvestigationReport", str(row["report_id"]))]}
            for row in ir_rows
            if row["case_id"] in case_uid_by_id and ("InvestigationReport", str(row["report_id"])) in entity_map
        ]
        n = _merge_edges(session, "HAS_EVIDENCE", has_evidence_edges)
        print(f"[neo4j-load] OK  HAS_EVIDENCE edges: {n}")

        # INVOLVES: Person -> Case, from EXT_AccusedIn / EXT_ComplainantIn
        involves_edges = []
        with pg.cursor() as cur:
            cur.execute("SELECT AccusedMasterID, CaseMasterID FROM EXT_AccusedIn")
            for row in cur.fetchall():
                a_uid = entity_map.get(("Accused", str(row["accusedmasterid"])))
                c_uid = case_uid_by_id.get(row["casemasterid"])
                if a_uid and c_uid:
                    involves_edges.append({"from_uid": a_uid, "to_uid": c_uid})
        with pg.cursor() as cur:
            cur.execute("SELECT ComplainantID, CaseMasterID FROM EXT_ComplainantIn")
            for row in cur.fetchall():
                c_uid_person = entity_map.get(("ComplainantDetails", str(row["complainantid"])))
                c_uid_case = case_uid_by_id.get(row["casemasterid"])
                if c_uid_person and c_uid_case:
                    involves_edges.append({"from_uid": c_uid_person, "to_uid": c_uid_case})
        n = _merge_edges(session, "INVOLVES", involves_edges)
        print(f"[neo4j-load] OK  INVOLVES edges: {n}")

        # MENTIONS: CaseMaster -> Account/UPIHandle/Device/PhoneNumber directly
        # (matching live -- see the note above), from EXT_Mentions. object_id is
        # a raw identifier string (account number, IMEI, ...), resolved via the
        # same normalization migrate_sqlite_to_pg.py used when it built each
        # object's *_normalized column.
        norm_by_type = {
            "accounts": (_norm_account, "Account", "account_number_normalized", "account_id"),
            "upis": (_norm_upi, "UPIHandle", "vpa_normalized", "upi_id"),
            "phones": (_norm_phone, "PhoneNumber", "number_normalized", "phone_id"),
            "imeis": (_norm_imei, "Device", "imei_normalized", "device_id"),
        }
        normalized_lookup: dict[str, dict[str, int]] = {}
        for _, (_, table, norm_col, pk_col) in norm_by_type.items():
            if table in normalized_lookup:
                continue
            with pg.cursor() as cur:
                cur.execute(f"SELECT {pk_col}, {norm_col} FROM {table}")
                normalized_lookup[table] = {row[norm_col]: row[pk_col] for row in cur.fetchall()}

        with pg.cursor() as cur:
            cur.execute("SELECT case_master_id, object_id, object_type FROM EXT_Mentions")
            mention_rows = cur.fetchall()
        # ips/wallets resolve straight off their natural PK -- no normalization and no
        # first-class table, unlike accounts/upis/phones/imeis above.
        ext_mention_types = {"ips": "EXT_IP", "wallets": "EXT_Wallet"}

        mentions_edges = []
        for row in mention_rows:
            object_type = (row["object_type"] or "").lower()
            from_uid = case_uid_by_id.get(row["case_master_id"])
            if not from_uid:
                continue

            if object_type in ext_mention_types:
                to_uid = ext_uid_by_key.get(ext_mention_types[object_type], {}).get(str(row["object_id"]))
                if to_uid:
                    mentions_edges.append({"from_uid": from_uid, "to_uid": to_uid})
                continue

            spec = norm_by_type.get(object_type)
            if not spec:
                continue
            norm_fn, table, _, pk_col = spec
            normalized = norm_fn(str(row["object_id"]))
            pk = normalized_lookup.get(table, {}).get(normalized)
            if pk is None:
                continue
            to_uid = object_entity_uid_by_pk.get(table, {}).get(pk)
            if to_uid:
                mentions_edges.append({"from_uid": from_uid, "to_uid": to_uid})
        n = _merge_edges(session, "MENTIONS", mentions_edges)
        print(f"[neo4j-load] OK  MENTIONS edges: {n}")

        # TRANSACTED_WITH: Account -> Account, from Transaction rows.
        # Carries the same properties live ingestion sets (processor.py::_build_edges)
        # and uses the same sha1 txn_key so historical and live edges are shaped
        # identically -- a time-ordered money query must not care which origin an edge
        # came from. Without amount/txn_timestamp these were bare arrows, and every
        # temporal money analysis (velocity, freezable funds, layering) was impossible
        # in Cypher.
        with pg.cursor() as cur:
            cur.execute(
                """
                SELECT from_account_id, to_account_id, amount, txn_timestamp, mode, utr_ref
                FROM Transaction
                WHERE from_account_id IS NOT NULL AND to_account_id IS NOT NULL
                """
            )
            txn_rows = cur.fetchall()
        account_uid_by_pk = object_entity_uid_by_pk.get("Account", {})
        txn_edges = []
        for row in txn_rows:
            from_uid = account_uid_by_pk.get(row["from_account_id"])
            to_uid = account_uid_by_pk.get(row["to_account_id"])
            if not (from_uid and to_uid):
                continue
            # amount is NUMERIC -> psycopg hands back Decimal, which the Bolt driver
            # can't serialize (same class of problem as the uuid.UUID note above).
            amount = float(row["amount"]) if row["amount"] is not None else None
            txn_timestamp = row["txn_timestamp"]
            txn_key = hashlib.sha1(
                f"{from_uid}|{to_uid}|{amount}|{txn_timestamp}".encode("utf-8")
            ).hexdigest()
            txn_edges.append({
                "from_uid": from_uid,
                "to_uid": to_uid,
                "txn_key": txn_key,
                "amount": amount,
                "txn_timestamp": txn_timestamp,
                "mode": row["mode"],
                "utr_ref": row["utr_ref"],
            })
        n = _merge_edges(
            session, "TRANSACTED_WITH", txn_edges,
            merge_key="txn_key", props=("amount", "txn_timestamp", "mode", "utr_ref"),
        )
        print(f"[neo4j-load] OK  TRANSACTED_WITH edges: {n}")

        # Account -> Wallet, the crypto cash-out hop. Same TRANSACTED_WITH type as the
        # account-to-account hops on purpose: a money-trail traversal shouldn't need to
        # know in advance that the trail ends in crypto -- it just walks TRANSACTED_WITH
        # and finds a :Wallet at the end.
        with pg.cursor() as cur:
            cur.execute(
                """
                SELECT from_account_id, to_wallet_address, amount, txn_timestamp, mode, utr_ref
                FROM Transaction
                WHERE from_account_id IS NOT NULL AND to_wallet_address IS NOT NULL
                """
            )
            wallet_txn_rows = cur.fetchall()
        wallet_uid_by_key = ext_uid_by_key.get("EXT_Wallet", {})
        wallet_edges = []
        for row in wallet_txn_rows:
            from_uid = account_uid_by_pk.get(row["from_account_id"])
            to_uid = wallet_uid_by_key.get(str(row["to_wallet_address"]))
            if not (from_uid and to_uid):
                continue
            amount = float(row["amount"]) if row["amount"] is not None else None
            txn_timestamp = row["txn_timestamp"]
            wallet_edges.append({
                "from_uid": from_uid,
                "to_uid": to_uid,
                "txn_key": hashlib.sha1(
                    f"{from_uid}|{to_uid}|{amount}|{txn_timestamp}".encode("utf-8")
                ).hexdigest(),
                "amount": amount,
                "txn_timestamp": txn_timestamp,
                "mode": row["mode"],
                "utr_ref": row["utr_ref"],
            })
        n = _merge_edges(
            session, "TRANSACTED_WITH", wallet_edges,
            merge_key="txn_key", props=("amount", "txn_timestamp", "mode", "utr_ref"),
        )
        print(f"[neo4j-load] OK  TRANSACTED_WITH (crypto cash-out) edges: {n}")

        # OWNS: Person -> Account/UPIHandle/PhoneNumber/Device, using holder_entity_uid
        # already resolved during migration (from EXT_Uses) -- no need to
        # re-parse EXT_Uses ourselves, Postgres already has the answer.
        # Device belongs here as much as the others: the shared-IMEI link is what
        # collapses an offender's aliases into one person (scenario 2), and without a
        # Person-[:OWNS]->(:Device) edge that traversal has nothing to walk.
        owns_edges = []
        for table, pk_col in [("Account", "account_id"), ("UPIHandle", "upi_id"), ("PhoneNumber", "phone_id"), ("Device", "device_id")]:
            with pg.cursor() as cur:
                cur.execute(f"SELECT {pk_col}, holder_entity_uid FROM {table} WHERE holder_entity_uid IS NOT NULL")
                for row in cur.fetchall():
                    obj_uid = object_entity_uid_by_pk.get(table, {}).get(row[pk_col])
                    if obj_uid and row["holder_entity_uid"]:
                        owns_edges.append({"from_uid": str(row["holder_entity_uid"]), "to_uid": obj_uid})
        n = _merge_edges(session, "OWNS", owns_edges)
        print(f"[neo4j-load] OK  OWNS edges: {n}")

    pg.close()
    driver.close()
    print("[neo4j-load] Completed successfully.")


if __name__ == "__main__":
    load()
