"""Full wipe of Postgres, Neo4j, Pinecone, and Stratus -- everything, not just
demo-tagged rows (see scripts/reset_demo_data.py for the narrower demo-only reset).

Used once to reach a known-clean slate before reloading historical data fresh
via migrate_sqlite_to_pg.py -> load_neo4j_from_pg.py -> load_pinecone_from_historical.py.

Destructive and irreversible. Dry-run by default (prints counts only).

Run:
    python scripts/wipe_all_data.py            # dry-run, counts only
    python scripts/wipe_all_data.py --yes       # actually delete
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

# Every table that holds case/entity/pipeline data (schema-config tables --
# SchemaDefinition/SchemaField/SchemaRelationship/AppConfig -- are deliberately
# excluded: they're static app config re-applied idempotently by
# migrate_sqlite_to_pg.py's seed_schema_config.sql step, not case data).
_ALL_TABLES = [
    # Master
    "State", "District", "UnitType", "Unit", "Rank", "Designation", "Employee",
    "Court", "CaseCategory", "GravityOffence", "CaseStatusMaster", "CrimeHead",
    "CrimeSubHead", "Act", "Section", "CrimeHeadActSection", "CasteMaster",
    "ReligionMaster", "OccupationMaster",
    # Core
    "CaseMaster", "ComplainantDetails", "Victim", "Accused", "ArrestSurrender",
    "ActSectionAssociation", "ChargesheetDetails",
    # Extension
    "EXT_IP", "EXT_Wallet", "EXT_Uses", "EXT_Mentions", "EXT_AccusedIn",
    "EXT_ComplainantIn", "EXT_CaseGeo", "EXT_VictimDetail", "EXT_AccusedDetail",
    "EXT_SubEvent", "EXT_LegalElement", "EXT_EvidenceType", "EXT_Precedent",
    "EXT_IPCSection",
    # Shared live/historical entity tables
    "Device", "Account", "UPIHandle", "PhoneNumber", "Transaction",
    "Evidence", "InvestigationReport", "EntityMap",
    # Live pipeline / demo-scenario bookkeeping
    "BatchUpload", "PipelineRun", "ReviewQueueItem", "IngestFileLoad",
    "IngestArtifact", "DemoResetOperation", "DemoScenarioState",
]


def wipe_postgres(dry_run: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    conn = psycopg.connect(_build_database_url(), autocommit=False)
    try:
        with conn.cursor() as cur:
            # Unquoted identifiers: DDL created these tables with unquoted mixed-case
            # names, which Postgres folds to lowercase -- quoting "State" here would
            # look for a literal mixed-case table that doesn't exist. Leaving these
            # unquoted lets Postgres fold them the same way at query time.
            for table in _ALL_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = int(cur.fetchone()[0])
            if not dry_run:
                # Single statement with CASCADE: Postgres resolves FK order itself,
                # no need to hand-order 40+ tables like reset_demo_data.py does for
                # its narrower, non-cascading scoped deletes.
                joined = ", ".join(_ALL_TABLES)
                cur.execute(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE")
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()
    return counts


def wipe_neo4j(dry_run: bool) -> int:
    if not _env("NEO4J_URI") or not _env("NEO4J_PASSWORD"):
        print("[wipe_all_data] Neo4j: SKIP (NEO4J_URI/NEO4J_PASSWORD not set)")
        return 0
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(_env("NEO4J_URI"), auth=(_env("NEO4J_USERNAME"), _env("NEO4J_PASSWORD")))
    try:
        with driver.session() as session:
            count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            if not dry_run and count:
                session.run("MATCH (n) DETACH DELETE n")
        return int(count)
    finally:
        driver.close()


def wipe_pinecone(dry_run: bool) -> int:
    if not _env("PINECONE_API_KEY"):
        print("[wipe_all_data] Pinecone: SKIP (PINECONE_API_KEY not set)")
        return 0
    from pinecone import Pinecone

    pc = Pinecone(api_key=_env("PINECONE_API_KEY"))
    index = pc.Index(_env("PINECONE_INDEX", "ksp-crime-intel"))
    stats = index.describe_index_stats()
    total = int(stats.get("total_vector_count", 0))
    if not dry_run and total:
        index.delete(delete_all=True)
    return total


def wipe_stratus(dry_run: bool) -> int:
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
    args = parser.parse_args()
    dry_run = not args.yes

    print(f"[wipe_all_data] mode={'DRY-RUN (no deletes)' if dry_run else 'DELETE -- FULL WIPE'}")

    pg_counts = wipe_postgres(dry_run)
    neo4j_count = wipe_neo4j(dry_run)
    pinecone_count = wipe_pinecone(dry_run)
    stratus_count = wipe_stratus(dry_run)

    print("\n--- Summary ---")
    for table, count in pg_counts.items():
        if count:
            print(f"Postgres {table:<24}: {count}")
    print(f"Neo4j nodes                    : {neo4j_count}")
    print(f"Pinecone vectors                : {pinecone_count}")
    print(f"Stratus raw/processed/archive objects: {stratus_count}")

    if dry_run:
        print("\nDry-run only. Re-run with --yes to actually delete.")
    else:
        print("\nWiped Postgres, Neo4j, Pinecone, and Stratus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
