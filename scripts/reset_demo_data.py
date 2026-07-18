"""Delete demo data only, leaving historical bootstrap data intact.

The live pipeline (raw/ -> processed/ -> archive/) only ever produces **demo** data.
Historical data lives under Stratus `historical/`, Neo4j nodes tagged
`origin:'historical'`, and Pinecone ids prefixed `historical::`; it is loaded by
migrate_sqlite_to_pg.py + load_neo4j_from_pg.py + load_pinecone_from_historical.py --
never by this pipeline. Scoping rules per store:

- Postgres: `PipelineRun`/`ReviewQueueItem`/`BatchUpload` are 100% demo (the live
  pipeline is their only writer). `Account`/`UPIHandle`/`PhoneNumber`/`Device`/
  `Transaction`/`Evidence`/`InvestigationReport`/`EntityMap`/`CaseMaster`/`Accused`/
  `Victim`/`ComplainantDetails`/`ActSectionAssociation` are shared with historical
  data (migrate_sqlite_to_pg.py populates them too), so those are scoped to the
  demo case_id set = PipelineRun.case_id UNION BatchUpload.case_id.
- Neo4j: nodes AND edges tagged `origin:'demo'`, deleted separately (a demo edge can
  join two historical nodes, which DETACH DELETE would never reach). Historical nodes
  and edges are keyed by `entity_uid` + `origin:'historical'` and stay untouched.
- Pinecone: vector ids prefixed `demo::` (`historical::` ids untouched).
- Stratus: everything under `raw/`, `processed/`, `archive/` (`historical/` untouched).

Shared objects are the subtle case and the reason this stays safe: the planted
aggregation account is ONE row / ONE node referenced by both origins. It survives a
wipe because the live pipeline never claims a pre-existing row (it leaves
source_evidence_id NULL and origin 'historical' -- see processor.py
_stamp_source_evidence and _load_graph), so neither scoping rule below matches it.

Reads the same `.env` as the rest of the app; does not depend on the FastAPI backend.

Run (dry-run by default, prints counts only):
    python scripts/reset_demo_data.py

Actually delete:
    python scripts/reset_demo_data.py --yes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from catalyst_functions.ingest_processor.pipeline.processor import (  # noqa: E402
    _build_database_url,
    _env,
    _stratus_bucket,
)

# (table, pk_column, extra_or_clause) — pk matched against Evidence.evidence_id for
# demo case_ids; Account additionally matches its own linked_case_id.
_EVIDENCE_LINKED_TABLES = [
    ("Account", "account_id", "t.linked_case_id = ANY(%(case_ids)s)"),
    ("UPIHandle", "upi_id", None),
    ("PhoneNumber", "phone_id", None),
    ("Device", "device_id", None),
]
_PERSON_TABLES = [("Accused", "AccusedMasterID"), ("Victim", "VictimMasterID"), ("ComplainantDetails", "ComplainantID")]


def _demo_case_ids(cur) -> list[int]:
    cur.execute(
        """
        SELECT DISTINCT case_id FROM PipelineRun WHERE case_id IS NOT NULL
        UNION
        SELECT DISTINCT case_id FROM BatchUpload WHERE case_id IS NOT NULL
        """
    )
    return [int(r[0]) for r in cur.fetchall()]


def _collect_demo_entity_uids(cur, case_ids: list[int]) -> list[str]:
    """Must run BEFORE any demo row is deleted: EntityMap.sql_table/sql_pk is a plain
    text pointer (no DB-level FK), so the only way to know which EntityMap rows belong
    to the demo case set is to join against the still-existing object rows now."""
    uids: set[str] = set()

    cur.execute("SELECT entity_uid FROM EntityMap WHERE sql_table = 'CaseMaster' AND sql_pk = ANY(%s)", ([str(c) for c in case_ids],))
    uids.update(str(r[0]) for r in cur.fetchall())

    for table, pk_col in _PERSON_TABLES:
        cur.execute(
            f"""
            SELECT em.entity_uid FROM EntityMap em
            JOIN {table} t ON em.sql_table = %s AND em.sql_pk = t.{pk_col}::text
            WHERE t.CaseMasterID = ANY(%s)
            """,
            (table, case_ids),
        )
        uids.update(str(r[0]) for r in cur.fetchall())

    cur.execute(
        """
        SELECT em.entity_uid FROM EntityMap em
        JOIN Evidence e ON em.sql_table = 'Evidence' AND em.sql_pk = e.evidence_id::text
        WHERE e.case_id = ANY(%s)
        """,
        (case_ids,),
    )
    uids.update(str(r[0]) for r in cur.fetchall())

    cur.execute(
        """
        SELECT em.entity_uid FROM EntityMap em
        JOIN InvestigationReport ir ON em.sql_table = 'InvestigationReport' AND em.sql_pk = ir.report_id::text
        WHERE ir.case_id = ANY(%s)
        """,
        (case_ids,),
    )
    uids.update(str(r[0]) for r in cur.fetchall())

    for table, pk_col, extra in _EVIDENCE_LINKED_TABLES:
        where_extra = f" OR {extra}" if extra else ""
        cur.execute(
            f"""
            SELECT em.entity_uid FROM EntityMap em
            JOIN {table} t ON em.sql_table = %(table)s AND em.sql_pk = t.{pk_col}::text
            WHERE t.source_evidence_id IN (SELECT evidence_id FROM Evidence WHERE case_id = ANY(%(case_ids)s)){where_extra}
            """,
            {"table": table, "case_ids": case_ids},
        )
        uids.update(str(r[0]) for r in cur.fetchall())

    return list(uids)


def reset_postgres(dry_run: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    conn = psycopg.connect(_build_database_url(), autocommit=False)
    try:
        with conn.cursor() as cur:
            case_ids = _demo_case_ids(cur)
            counts["demo_case_ids"] = len(case_ids)

            entity_uids = _collect_demo_entity_uids(cur, case_ids) if case_ids else []
            counts["EntityMap"] = len(entity_uids)

            def _count_and_delete(label: str, where_sql: str, params: dict) -> None:
                cur.execute(f"SELECT COUNT(*) FROM {label} WHERE {where_sql}", params)
                counts[label] = int(cur.fetchone()[0])
                if not dry_run and counts[label]:
                    cur.execute(f"DELETE FROM {label} WHERE {where_sql}", params)

            # FK-safe order: children before the parents they reference.
            _count_and_delete("ReviewQueueItem", "source_run_id IN (SELECT run_id FROM PipelineRun WHERE case_id = ANY(%(case_ids)s))", {"case_ids": case_ids})
            _count_and_delete("Transaction", "source_evidence_id IN (SELECT evidence_id FROM Evidence WHERE case_id = ANY(%(case_ids)s))", {"case_ids": case_ids})
            for table, _pk_col, extra in _EVIDENCE_LINKED_TABLES:
                where_extra = f" OR {extra}" if extra else ""
                _count_and_delete(
                    table,
                    f"source_evidence_id IN (SELECT evidence_id FROM Evidence WHERE case_id = ANY(%(case_ids)s)){where_extra.replace('t.', '')}",
                    {"case_ids": case_ids},
                )
            _count_and_delete("Evidence", "case_id = ANY(%(case_ids)s)", {"case_ids": case_ids})
            _count_and_delete("InvestigationReport", "case_id = ANY(%(case_ids)s)", {"case_ids": case_ids})

            if not dry_run and entity_uids:
                cur.execute("DELETE FROM EntityMap WHERE entity_uid = ANY(%s)", (entity_uids,))

            _count_and_delete("PipelineRun", "case_id = ANY(%(case_ids)s)", {"case_ids": case_ids})
            # BatchUpload.case_id is NULL until /process mints one onto PipelineRun (never
            # backfilled), so scoping by case_ids would leak never-processed uploads. The
            # table is 100% demo (never written by the historical migration) — delete all.
            _count_and_delete("BatchUpload", "TRUE", {"case_ids": case_ids})

            for table, pk_col in _PERSON_TABLES:
                _count_and_delete(table, "CaseMasterID = ANY(%(case_ids)s)", {"case_ids": case_ids})
            _count_and_delete("ActSectionAssociation", "CaseMasterID = ANY(%(case_ids)s)", {"case_ids": case_ids})
            _count_and_delete("CaseMaster", "CaseMasterID = ANY(%(case_ids)s)", {"case_ids": case_ids})

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()
    return counts


def reset_neo4j(dry_run: bool) -> tuple[int, int]:
    """Returns (demo nodes deleted, demo edges deleted).

    Edges are deleted separately, not just via DETACH DELETE of demo nodes. A demo run
    can create an edge whose BOTH endpoints are historical -- e.g. a TRANSACTED_WITH
    between two pre-existing accounts read out of an uploaded bank statement. Those
    endpoints survive the wipe (correctly), so DETACH DELETE never reaches the edge and
    it would accumulate across demo runs, inflating the historical money trail with
    leftovers from previous rehearsals.
    """
    if not _env("NEO4J_URI") or not _env("NEO4J_PASSWORD"):
        print("[reset_demo_data] Neo4j: SKIP (NEO4J_URI/NEO4J_PASSWORD not set)")
        return 0, 0
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(_env("NEO4J_URI"), auth=(_env("NEO4J_USERNAME"), _env("NEO4J_PASSWORD")))
    try:
        with driver.session() as session:
            nodes = session.run("MATCH (n {origin: 'demo'}) RETURN count(n) AS c").single()["c"]
            edges = session.run("MATCH ()-[r {origin: 'demo'}]->() RETURN count(r) AS c").single()["c"]
            if not dry_run:
                if edges:
                    session.run("MATCH ()-[r {origin: 'demo'}]->() DELETE r")
                if nodes:
                    session.run("MATCH (n {origin: 'demo'}) DETACH DELETE n")
        return int(nodes), int(edges)
    finally:
        driver.close()


def reset_pinecone(dry_run: bool) -> int:
    if not _env("PINECONE_API_KEY"):
        print("[reset_demo_data] Pinecone: SKIP (PINECONE_API_KEY not set)")
        return 0
    from pinecone import Pinecone

    pc = Pinecone(api_key=_env("PINECONE_API_KEY"))
    index = pc.Index(_env("PINECONE_INDEX", "ksp-crime-intel"))
    demo_ids = [vector.id for page in index.list(prefix="demo::") for vector in page.vectors]
    if not dry_run and demo_ids:
        index.delete(ids=demo_ids)
    return len(demo_ids)


def reset_stratus(dry_run: bool) -> int:
    bucket = _stratus_bucket()
    deleted = 0
    for prefix in ("raw/", "processed/", "archive/"):
        next_token = None
        while True:
            page = bucket.list_paged_objects(prefix=prefix, next_token=next_token)
            for obj in page["contents"]:
                key = obj.to_dict().get("key") if hasattr(obj, "to_dict") else obj.get("key")
                if not key:
                    continue
                deleted += 1
                if not dry_run:
                    bucket.delete_object(key)
            if not page.get("truncated"):
                break
            next_token = page.get("next_continuation_token")
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="Actually delete. Without this flag, only counts are printed (dry-run).")
    parser.add_argument("--dry-run", action="store_true", help="Explicit no-op: this is the default when --yes is omitted.")
    args = parser.parse_args()
    dry_run = not args.yes

    print(f"[reset_demo_data] mode={'DRY-RUN (no deletes)' if dry_run else 'DELETE'}")

    pg_counts = reset_postgres(dry_run)
    neo4j_nodes, neo4j_edges = reset_neo4j(dry_run)
    pinecone_count = reset_pinecone(dry_run)
    stratus_count = reset_stratus(dry_run)

    print("\n--- Summary ---")
    print(f"Postgres demo case_ids: {pg_counts.get('demo_case_ids', 0)}")
    for label, count in pg_counts.items():
        if label != "demo_case_ids":
            print(f"Postgres {label:<24}: {count}")
    print(f"Neo4j demo nodes         : {neo4j_nodes}")
    print(f"Neo4j demo edges         : {neo4j_edges}")
    print(f"Pinecone demo vectors    : {pinecone_count}")
    print(f"Stratus raw/processed/archive objects: {stratus_count}")

    if dry_run:
        print("\nDry-run only. Re-run with --yes to actually delete.")
    else:
        print("\nDeleted demo data across Postgres, Neo4j, Pinecone, and Stratus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
