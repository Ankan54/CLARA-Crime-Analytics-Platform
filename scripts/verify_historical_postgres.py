"""verify_historical_postgres.py -- durable check that historical data loaded
into Postgres by migrate_sqlite_to_pg.py is complete and internally consistent.

Three things, in order:
  1. Row counts for the tables migrate_sqlite_to_pg.py populates are within
     +-10% of data_generation/config.py's TARGET_* constants (same tolerance
     validate.py already uses for the offline sqlite artifacts).
  2. EntityMap referential integrity: no duplicate (sql_table, sql_pk) pairs,
     no EntityMap row pointing at a sql_pk that doesn't actually exist in its
     sql_table.
  3. A handful of known planted shared identifiers (identifier_pool.py) each
     resolve to more than one historical case -- the actual thing the demo
     scenarios depend on.

Exit code 0 and "ALL CHECKS PASSED" iff everything holds. Read-only.

Usage:
    python scripts/verify_historical_postgres.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from backend.migrations.migrate_sqlite_to_pg import (  # noqa: E402
    SQLITE_PATH_DEFAULT, _build_conninfo, _norm_account, _norm_imei, _norm_phone, _norm_upi,
)
from data_generation import config  # noqa: E402
from data_generation import identifier_pool as pool  # noqa: E402

TOLERANCE = config.VOLUME_TOLERANCE  # 0.10

# (table, TARGET_* constant, label)
_VOLUME_CHECKS = [
    ("CaseMaster", config.TARGET_FIRS_HISTORICAL, "CaseMaster (hist FIRs)"),
    ("Account", config.TARGET_ACCOUNTS, "Account"),
    ("UPIHandle", config.TARGET_UPIS, "UPIHandle"),
    ("Device", config.TARGET_DEVICES, "Device"),
    ("PhoneNumber", config.TARGET_PHONES, "PhoneNumber"),
    ("Transaction", config.TARGET_TRANSACTIONS, "Transaction"),
    ("InvestigationReport", config.TARGET_INVESTIGATION_REPORTS_HISTORICAL, "InvestigationReport"),
]

# Account/UPIHandle/Device/PhoneNumber are genuinely shared between historical
# and live data (that's the point), so "historical count" can't just exclude
# live case_ids -- a live-only object (e.g. a scenario's controller UPI/IMEI)
# needs excluding even though it has no case_id at all. Ground truth is
# whether it actually appears in the sqlite seed, same approach
# load_neo4j_from_pg.py uses.
_SHARED_OBJECT_TABLES = {
    "Account": ("account_number_raw", "EXT_Account", "AccountNo", _norm_account),
    "UPIHandle": ("vpa_raw", "EXT_UPI", "VPA", _norm_upi),
    "Device": ("imei_raw", "EXT_Device", "IMEI", _norm_imei),
    "PhoneNumber": ("number_raw", "EXT_Phone", "Number", _norm_phone),
}

# (table, sql_pk_column) -- every table an EntityMap row can point at.
_ENTITY_TABLES = [
    ("CaseMaster", "CaseMasterID"),
    ("Accused", "AccusedMasterID"),
    ("ComplainantDetails", "ComplainantID"),
    ("Victim", "VictimMasterID"),
    ("Account", "account_id"),
    ("UPIHandle", "upi_id"),
    ("Device", "device_id"),
    ("PhoneNumber", "phone_id"),
    ("Evidence", "evidence_id"),
    ("InvestigationReport", "report_id"),
]

# (object_type in EXT_Mentions, object_id, min expected distinct historical cases, label)
_MENTION_CHECKS = [
    ("upis", pool.UPI_02, 2, "scenario2 shared UPI (many-names)"),
    ("phones", pool.PHONE_02, 2, "scenario2 shared phone (many-names)"),
    ("accounts", pool.BRIDGE_ACC_03["account_no"], 1, "scenario3 bridge account (follow-money)"),
]


def _fail(msg: str, failures: list[str]) -> None:
    failures.append(msg)
    print(f"  FAIL  {msg}")


def _live_case_ids(cur) -> set[int]:
    cur.execute("SELECT DISTINCT case_id FROM PipelineRun WHERE case_id IS NOT NULL")
    return {row["case_id"] for row in cur.fetchall()}


def check_volumes(cur, failures: list[str]) -> None:
    print("\n[1/3] Row counts vs config.py TARGET_* (+-10%, historical-only)")
    # Postgres is the live database -- once any demo scenario has been
    # uploaded, these tables also contain live rows (e.g. CaseMaster gets the
    # live case, Device may gain a scenario's controller IMEI). TARGET_*
    # describes the historical baseline only, so exclude live case_ids (every
    # live case has exactly one PipelineRun row; historical cases never do)
    # before comparing -- confirmed live this check false-failed on Device
    # after scenario 1's live upload added its controller IMEI otherwise.
    live_case_ids = _live_case_ids(cur)
    live_ids_sql = "'{" + ",".join(str(i) for i in live_case_ids) + "}'::int[]" if live_case_ids else "'{}'::int[]"

    sqlite_conn = sqlite3.connect(SQLITE_PATH_DEFAULT)
    sqlite_conn.row_factory = sqlite3.Row

    case_scoped = {"CaseMaster": "CaseMasterID", "InvestigationReport": "case_id"}
    for table, target, label in _VOLUME_CHECKS:
        if table in case_scoped:
            cur.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE {case_scoped[table]} != ALL({live_ids_sql})")
            actual = cur.fetchone()["c"]
        elif table in _SHARED_OBJECT_TABLES:
            raw_col, sqlite_table, sqlite_col, norm_fn = _SHARED_OBJECT_TABLES[table]
            historical_values = {norm_fn(r[sqlite_col]) for r in sqlite_conn.execute(f"SELECT {sqlite_col} FROM {sqlite_table}")}
            cur.execute(f"SELECT {raw_col} AS v FROM {table}")
            actual = sum(1 for row in cur.fetchall() if norm_fn(row["v"]) in historical_values)
        else:
            cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
            actual = cur.fetchone()["c"]
        lo, hi = target * (1 - TOLERANCE), target * (1 + TOLERANCE)
        if lo <= actual <= hi:
            print(f"  OK    {label}: {actual} (target {target})")
        else:
            _fail(f"{label}: {actual} rows, expected ~{target} (+-10%)", failures)
    sqlite_conn.close()

    # Evidence has no dedicated TARGET_* -- it's structurally one row per FIR
    # (always) + one per InvestigationReport (where one exists), so check the
    # invariant directly instead of a magic number. Scoped historical-only
    # the same way (uploaded_by is set for every historical Evidence row).
    cur.execute("SELECT COUNT(*) AS c FROM Evidence WHERE uploaded_by = 'historical-seed'")
    evidence_count = cur.fetchone()["c"]
    cur.execute(f"SELECT COUNT(*) AS c FROM CaseMaster WHERE CaseMasterID != ALL({live_ids_sql})")
    case_count = cur.fetchone()["c"]
    cur.execute(f"SELECT COUNT(*) AS c FROM InvestigationReport WHERE case_id != ALL({live_ids_sql})")
    ir_count = cur.fetchone()["c"]
    expected_evidence = case_count + ir_count
    if evidence_count == expected_evidence:
        print(f"  OK    Evidence: {evidence_count} (= {case_count} FIRs + {ir_count} IRs)")
    else:
        _fail(f"Evidence: {evidence_count} rows, expected {expected_evidence} (= FIRs + IRs)", failures)


def check_entity_map(cur, failures: list[str]) -> None:
    print("\n[2/3] EntityMap referential integrity")
    cur.execute(
        """
        SELECT sql_table, sql_pk, COUNT(*) AS c FROM EntityMap
        GROUP BY sql_table, sql_pk HAVING COUNT(*) > 1
        """
    )
    dupes = cur.fetchall()
    if dupes:
        _fail(f"{len(dupes)} duplicate (sql_table, sql_pk) pairs in EntityMap, e.g. {dupes[0]}", failures)
    else:
        print("  OK    no duplicate (sql_table, sql_pk) pairs")

    orphans_total = 0
    for table, pk_col in _ENTITY_TABLES:
        cur.execute(
            f"""
            SELECT em.sql_pk FROM EntityMap em
            WHERE em.sql_table = %s
              AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.{pk_col}::text = em.sql_pk)
            """,
            (table,),
        )
        orphans = cur.fetchall()
        if orphans:
            orphans_total += len(orphans)
            _fail(f"{len(orphans)} EntityMap rows point at missing {table} rows, e.g. sql_pk={orphans[0]['sql_pk']}", failures)
    if not orphans_total:
        print(f"  OK    no dangling EntityMap pointers across {len(_ENTITY_TABLES)} tables")


def check_planted_identifiers(cur, failures: list[str]) -> None:
    print("\n[3/3] Planted shared identifiers resolve to multiple historical cases")
    for object_type, object_id, min_cases, label in _MENTION_CHECKS:
        cur.execute(
            "SELECT COUNT(DISTINCT case_master_id) AS c FROM EXT_Mentions WHERE object_type = %s AND object_id = %s",
            (object_type, object_id),
        )
        distinct_cases = cur.fetchone()["c"]
        if distinct_cases >= min_cases:
            print(f"  OK    {label} ({object_id}): {distinct_cases} distinct cases mention it")
        else:
            _fail(f"{label} ({object_id}): only {distinct_cases} distinct cases mention it, expected >= {min_cases}", failures)

    # AGG_ACC_01 deliberately has NO direct EXT_Mentions/owner -- it's reached
    # only via Transaction adjacency from each case's own collection account
    # (the "aggregation hop" scenario 1 is built around). Check that path
    # instead of a direct mention.
    agg_account_no = pool.AGG_ACC_01["account_no"]
    cur.execute(
        """
        WITH agg AS (
            SELECT account_id FROM Account WHERE account_number_normalized = %(acc)s
        ),
        adjacent_accounts AS (
            SELECT DISTINCT
                CASE WHEN t.to_account_id = agg.account_id THEN t.from_account_id ELSE t.to_account_id END AS account_id
            FROM Transaction t, agg
            WHERE t.from_account_id = agg.account_id OR t.to_account_id = agg.account_id
        )
        SELECT COUNT(DISTINCT em.case_master_id) AS c
        FROM EXT_Mentions em
        JOIN Account a ON a.account_number_normalized = em.object_id AND em.object_type = 'accounts'
        JOIN adjacent_accounts aa ON aa.account_id = a.account_id
        """,
        {"acc": agg_account_no},
    )
    reachable_cases = cur.fetchone()["c"]
    if reachable_cases >= 3:
        print(f"  OK    scenario1 aggregation account ({agg_account_no}): {reachable_cases} cases reachable via transaction adjacency")
    else:
        _fail(f"scenario1 aggregation account ({agg_account_no}): only {reachable_cases} cases reachable via transaction adjacency, expected >= 3", failures)


def main() -> int:
    conn = psycopg.connect(_build_conninfo(__import__("os").getenv("DB_NAME", "postgres")), row_factory=dict_row, prepare_threshold=None)
    failures: list[str] = []
    try:
        with conn.cursor() as cur:
            check_volumes(cur, failures)
            check_entity_map(cur, failures)
            check_planted_identifiers(cur, failures)
    finally:
        conn.close()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s) failed.")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
