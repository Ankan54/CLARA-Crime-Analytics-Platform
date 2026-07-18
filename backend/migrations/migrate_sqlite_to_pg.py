from __future__ import annotations

import argparse
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg import sql


ROOT = Path(__file__).resolve().parents[2]
SQLITE_PATH_DEFAULT = ROOT / "sample_data" / "historical" / "db" / "ksp.sqlite"
SCHEMA_SQL_PATH = ROOT / "backend" / "migrations" / "schema_pg.sql"
SEED_SQL_PATH = ROOT / "backend" / "migrations" / "seed_schema_config.sql"
# Demo-scenario tables (DemoScenarioState/DemoResetOperation/IngestArtifact/
# IngestFileLoad) + scenario_key/scenario_generation columns on BatchUpload/
# PipelineRun. Confirmed live this was never applied here before -- PipelineRun
# was missing scenario_key even though the 4 new tables and BatchUpload's
# columns existed (someone must have applied this file, or parts of it,
# manually against this database at some point; migrate_sqlite_to_pg.py never
# ran it, so a from-scratch database -- or one that lost the column some other
# way -- would 500 on /demo-scenarios/{key}/prepare with "column scenario_key
# does not exist").
DEMO_SCENARIO_SQL_PATH = ROOT / "backend" / "migrations" / "002_demo_scenario_tables.sql"
ASSISTANT_SQL_PATH = ROOT / "backend" / "migrations" / "003_assistant_tables.sql"


MASTER_TABLES = [
    "State",
    "District",
    "UnitType",
    "Unit",
    "Rank",
    "Designation",
    "Employee",
    "Court",
    "CaseCategory",
    "GravityOffence",
    "CaseStatusMaster",
    "CrimeHead",
    "CrimeSubHead",
    "Act",
    "Section",
    "CrimeHeadActSection",
    "CasteMaster",
    "ReligionMaster",
    "OccupationMaster",
]

CORE_TABLES = [
    "CaseMaster",
    "ComplainantDetails",
    "Victim",
    "Accused",
    "ArrestSurrender",
    "ActSectionAssociation",
    "ChargesheetDetails",
]

KEPT_EXT_TABLES = [
    "EXT_IP",
    "EXT_Wallet",
    "EXT_Uses",
    "EXT_Mentions",
    "EXT_AccusedIn",
    "EXT_ComplainantIn",
    "EXT_CaseGeo",
    "EXT_VictimDetail",
    "EXT_AccusedDetail",
    "EXT_SubEvent",
    "EXT_LegalElement",
    "EXT_EvidenceType",
    "EXT_Precedent",
    "EXT_IPCSection",
    "EXT_SectionMap",
    "EXT_ElementSatisfiedBy",
]


def _coerce(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _build_conninfo(db_name: str) -> str:
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres").strip("\"'")
    sslmode = os.getenv("DB_SSL", "require")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}?sslmode={sslmode}"


def _ensure_target_database(target_db: str, maintenance_db: str) -> None:
    # prepare_threshold=None: Supabase's transaction-mode pooler (port 6543) can
    # route consecutive statements to different backend connections, so a server-
    # side prepared statement from one backend can collide with -- or vanish from
    # under -- a later statement on another (surfaced live as "prepared statement
    # _pg3_1 already exists" on a second migration run). Documented in CLAUDE.md.
    with psycopg.connect(_build_conninfo(maintenance_db), autocommit=True, prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            exists = cur.fetchone() is not None
            if not exists:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
                print(f"[migrate] Created database: {target_db}")
            else:
                print(f"[migrate] Database already exists: {target_db}")


def _apply_sql_file(conn: psycopg.Connection, path: Path) -> None:
    sql_text = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql_text)
    conn.commit()
    print(f"[migrate] Applied SQL file: {path.name}")


def _sqlite_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cur = conn.execute(f"SELECT * FROM {table}")
    columns = [desc[0] for desc in cur.description]
    rows = []
    for row in cur.fetchall():
        rows.append({columns[i]: _coerce(row[i]) for i in range(len(columns))})
    return rows


def _delete_table(cur: psycopg.Cursor, table: str) -> None:
    cur.execute(f"DELETE FROM {table}")


def _insert_rows(cur: psycopg.Cursor, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join(["%s"] * len(columns))
    col_sql = ", ".join(columns)
    stmt = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"
    payload = [tuple(row.get(col) for col in columns) for row in rows]
    cur.executemany(stmt, payload)


def _norm_account(raw: str | None) -> str | None:
    if not raw:
        return None
    return "".join(raw.split())


def _norm_upi(raw: str | None) -> str | None:
    return raw.strip().lower() if raw else None


def _norm_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _norm_imei(raw: str | None) -> str | None:
    if not raw:
        return None
    return "".join(ch for ch in raw if ch.isdigit())


def _load_direct_tables(src: sqlite3.Connection, dst: psycopg.Connection, results: list[dict[str, Any]]) -> None:
    # Each table gets its own commit/rollback so one bad table (bad row, FK
    # violation, whatever) can't silently blank out every table after it --
    # confirmed live this was exactly why Account/UPIHandle/Device/Phone/
    # Transaction stayed empty while CaseMaster/Victim/ComplainantDetails
    # (committed earlier in the old single-transaction loop) persisted.
    # One CASCADE truncate up front, not a per-table DELETE inside the loop below:
    # the loop's table order is insert-safe (parents before children) but that's
    # backwards for DELETE (a second consecutive run hit FK violations deleting
    # State while District still referenced it, since District's own delete
    # hadn't run yet). CASCADE resolves the FK order automatically; a fresh
    # database just no-ops here.
    try:
        with dst.cursor() as cur:
            joined = ", ".join(MASTER_TABLES + CORE_TABLES + KEPT_EXT_TABLES)
            cur.execute(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE")
        dst.commit()
    except Exception as exc:
        dst.rollback()
        print(f"[migrate] FAIL  pre-truncate direct tables: {exc}")

    for table in MASTER_TABLES + CORE_TABLES + KEPT_EXT_TABLES:
        try:
            with dst.cursor() as cur:
                rows = _sqlite_rows(src, table)
                _insert_rows(cur, table, rows)
            dst.commit()
            print(f"[migrate] OK    {table}: {len(rows)} rows")
            results.append({"table": table, "status": "ok", "rows": len(rows), "error": None})
        except Exception as exc:
            dst.rollback()
            print(f"[migrate] FAIL  {table}: {exc}")
            results.append({"table": table, "status": "failed", "rows": 0, "error": str(exc)})


def _migrate_transformed_tables(src: sqlite3.Connection, dst: psycopg.Connection, results: list[dict[str, Any]]) -> None:
    account_rows = _sqlite_rows(src, "EXT_Account")
    upi_rows = _sqlite_rows(src, "EXT_UPI")
    phone_rows = _sqlite_rows(src, "EXT_Phone")
    device_rows = _sqlite_rows(src, "EXT_Device")
    transaction_rows = _sqlite_rows(src, "EXT_Transaction")
    uses_rows = _sqlite_rows(src, "EXT_Uses")
    ir_rows = _sqlite_rows(src, "EXT_InvestigationReport")
    wallet_addresses = {str(r["Address"]) for r in _sqlite_rows(src, "EXT_Wallet")}

    account_case_map: dict[str, int] = {}
    for row in _sqlite_rows(src, "EXT_Mentions"):
        # object_type is always the plural lowercase form -- it's literally the
        # dict key from FIR.identifiers_mentioned ("accounts"/"upis"/"imeis"/...,
        # confirmed against the live sqlite data). The singular "account" here
        # never matched anything, so this map was silently populated only by
        # the Transaction fallback below.
        if (row.get("object_type") or "").lower() == "accounts" and row.get("object_id") and row.get("case_master_id"):
            account_case_map.setdefault(str(row["object_id"]), int(row["case_master_id"]))
    for row in transaction_rows:
        case_id = row.get("CaseMasterID")
        if case_id:
            if row.get("FromAccount"):
                account_case_map.setdefault(str(row["FromAccount"]), int(case_id))
            if row.get("ToAccount"):
                account_case_map.setdefault(str(row["ToAccount"]), int(case_id))

    # Deletes are cheap and all-or-nothing is fine here -- there's no partial
    # state worth preserving for a DELETE, unlike the inserts below.
    with dst.cursor() as cur:
        for table in ["ReviewQueueItem", "Transaction", "PhoneNumber", "UPIHandle", "Account", "Device", "Evidence", "InvestigationReport", "EntityMap"]:
            _delete_table(cur, table)
    dst.commit()

    # Each block below commits/rolls back independently so a bad row in one
    # table (e.g. Transaction) can't blank out tables that already succeeded
    # (e.g. Account) -- this was the actual root cause of Account/UPIHandle/
    # PhoneNumber/Device/Transaction staying empty while CaseMaster et al
    # persisted: the old code ran this whole function as one transaction with
    # a single commit at the very end, and zero try/except anywhere in it.
    # Maps are declared up front so a failed block just leaves its map empty
    # instead of raising NameError in a block that depends on it.
    entity_map_by_ref: dict[tuple[str, str], str] = {}
    device_map: dict[str, tuple[int, str]] = {}
    account_map: dict[str, tuple[int, str]] = {}
    upi_map: dict[str, tuple[int, str]] = {}
    phone_map: dict[str, tuple[int, str]] = {}

    # CaseMaster rows are already committed by _load_direct_tables by the time
    # this runs, but never got an EntityMap row minted anywhere -- live
    # ingestion mints one via _ensure_entity("CaseMaster", case_id, "Event",
    # "Case"), so without this, no historical case could ever get a Case node,
    # which means no HAS_EVIDENCE or INVOLVES edges could resolve either.
    try:
        with dst.cursor() as cur:
            cur.execute("SELECT CaseMasterID FROM CaseMaster")
            case_ids = [row[0] for row in cur.fetchall()]
            for case_id in case_ids:
                entity_uid = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO EntityMap(entity_uid, entity_type, pole_subtype, sql_table, sql_pk, status, created_at, updated_at)
                    VALUES (%s, 'Event', 'Case', 'CaseMaster', %s, 'active', NOW(), NOW())
                    """,
                    (entity_uid, str(case_id)),
                )
        dst.commit()
        print(f"[migrate] OK    EntityMap(CaseMaster): {len(case_ids)} rows")
        results.append({"table": "EntityMap(CaseMaster)", "status": "ok", "rows": len(case_ids), "error": None})
    except Exception as exc:
        dst.rollback()
        print(f"[migrate] FAIL  EntityMap(CaseMaster): {exc}")
        results.append({"table": "EntityMap(CaseMaster)", "status": "failed", "rows": 0, "error": str(exc)})

    # EXT_Uses.from_person_id (e.g. "P_SCN2_A1") is a case-scoped natural key, not
    # an AccusedMasterID -- resolved below via (CaseMasterID, PersonID) lookup.
    accused_by_case_person: dict[str, str] = {}

    try:
        with dst.cursor() as cur:
            count = 0
            for person_table, pk_col, pole_subtype in [
                ("Accused", "AccusedMasterID", "Accused"),
                ("ComplainantDetails", "ComplainantID", "Complainant"),
                ("Victim", "VictimMasterID", "Victim"),
            ]:
                for row in _sqlite_rows(src, person_table):
                    pk_val = row.get(pk_col)
                    if pk_val is None:
                        continue
                    entity_uid = str(uuid.uuid4())
                    cur.execute(
                        """
                        INSERT INTO EntityMap(entity_uid, entity_type, pole_subtype, sql_table, sql_pk, status, created_at, updated_at)
                        VALUES (%s, 'Person', %s, %s, %s, 'active', NOW(), NOW())
                        """,
                        (entity_uid, pole_subtype, person_table, str(pk_val)),
                    )
                    entity_map_by_ref[(person_table, str(pk_val))] = entity_uid
                    count += 1
                    if person_table == "Accused" and row.get("CaseMasterID") is not None:
                        # Keyed by case only, not (case, PersonID): PersonID here is
                        # case-local ("A1" = first accused *in this case*), but
                        # EXT_Uses.from_person_id's trailing number is a scenario-
                        # global accused index ("P_SCN2_A2" = 2nd accused *in the
                        # scenario*) -- confirmed live these numbering schemes only
                        # coincide by chance for the first row. Every case in the
                        # current dataset has at most one Accused row, so CaseMasterID
                        # alone is an unambiguous join key; would need re-keying if a
                        # case with 2+ accused start needing EXT_Uses resolution.
                        accused_by_case_person[str(row["CaseMasterID"])] = entity_uid
        dst.commit()
        print(f"[migrate] OK    EntityMap(Person): {count} rows")
        results.append({"table": "EntityMap(Person)", "status": "ok", "rows": count, "error": None})
    except Exception as exc:
        dst.rollback()
        print(f"[migrate] FAIL  EntityMap(Person): {exc}")
        results.append({"table": "EntityMap(Person)", "status": "failed", "rows": 0, "error": str(exc)})

    try:
        evidence_rows = _sqlite_rows(src, "EXT_Evidence")
        with dst.cursor() as cur:
            for row in evidence_rows:
                cur.execute(
                    """
                    INSERT INTO Evidence(case_id, doc_type, file_ref, original_filename, extraction_status, uploaded_by, created_at)
                    VALUES (%s, %s, %s, %s, %s, 'historical-seed', NOW())
                    RETURNING evidence_id
                    """,
                    (
                        row.get("CaseMasterID"),
                        row.get("DocType"),
                        row.get("FileRef"),
                        row.get("OriginalFilename"),
                        row.get("ExtractionStatus") or "success",
                    ),
                )
                evidence_id = int(cur.fetchone()[0])
                entity_uid = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO EntityMap(entity_uid, entity_type, pole_subtype, sql_table, sql_pk, status, created_at, updated_at)
                    VALUES (%s, 'Object', 'Evidence', 'Evidence', %s, 'active', NOW(), NOW())
                    """,
                    (entity_uid, str(evidence_id)),
                )
        dst.commit()
        print(f"[migrate] OK    Evidence: {len(evidence_rows)} rows")
        results.append({"table": "Evidence", "status": "ok", "rows": len(evidence_rows), "error": None})
    except Exception as exc:
        dst.rollback()
        print(f"[migrate] FAIL  Evidence: {exc}")
        results.append({"table": "Evidence", "status": "failed", "rows": 0, "error": str(exc)})

    try:
        with dst.cursor() as cur:
            for row in device_rows:
                cur.execute(
                    """
                    INSERT INTO Device(imei_raw, imei_normalized, model, holder_name_raw, source_evidence_id, created_at)
                    VALUES (%s, %s, NULL, NULL, NULL, NOW())
                    RETURNING device_id
                    """,
                    (row.get("IMEI"), _norm_imei(row.get("IMEI"))),
                )
                device_id = int(cur.fetchone()[0])
                entity_uid = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO EntityMap(entity_uid, entity_type, pole_subtype, sql_table, sql_pk, status, created_at, updated_at)
                    VALUES (%s, 'Object', 'Device', 'Device', %s, 'active', NOW(), NOW())
                    """,
                    (entity_uid, str(device_id)),
                )
                device_map[str(row.get("IMEI"))] = (device_id, entity_uid)
        dst.commit()
        print(f"[migrate] OK    Device: {len(device_rows)} rows")
        results.append({"table": "Device", "status": "ok", "rows": len(device_rows), "error": None})
    except Exception as exc:
        dst.rollback()
        device_map.clear()
        print(f"[migrate] FAIL  Device: {exc}")
        results.append({"table": "Device", "status": "failed", "rows": 0, "error": str(exc)})

    try:
        with dst.cursor() as cur:
            for row in account_rows:
                account_no = str(row.get("AccountNo"))
                cur.execute(
                    """
                    INSERT INTO Account(
                        account_number_raw, account_number_normalized, ifsc, bank_name, branch_name, branch_district,
                        account_type, holder_name_raw, holder_entity_uid, account_open_date, kyc_name, is_flagged_mule,
                        linked_case_id, source_evidence_id, created_at
                    )
                    VALUES (%s, %s, %s, %s, NULL, %s, %s, %s, NULL, %s, %s, %s, %s, NULL, NOW())
                    RETURNING account_id
                    """,
                    (
                        account_no,
                        _norm_account(account_no),
                        row.get("IFSC"),
                        row.get("Bank"),
                        row.get("BranchDistrict"),
                        row.get("AccountType"),
                        row.get("KYCName"),
                        row.get("OpenDate"),
                        row.get("KYCName"),
                        bool(int(row.get("IsFlaggedMule") or 0)),
                        account_case_map.get(account_no),
                    ),
                )
                account_id = int(cur.fetchone()[0])
                entity_uid = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO EntityMap(entity_uid, entity_type, pole_subtype, sql_table, sql_pk, status, created_at, updated_at)
                    VALUES (%s, 'Object', 'Account', 'Account', %s, 'active', NOW(), NOW())
                    """,
                    (entity_uid, str(account_id)),
                )
                account_map[account_no] = (account_id, entity_uid)
        dst.commit()
        print(f"[migrate] OK    Account: {len(account_rows)} rows")
        results.append({"table": "Account", "status": "ok", "rows": len(account_rows), "error": None})
    except Exception as exc:
        dst.rollback()
        account_map.clear()
        print(f"[migrate] FAIL  Account: {exc}")
        results.append({"table": "Account", "status": "failed", "rows": 0, "error": str(exc)})

    try:
        with dst.cursor() as cur:
            for row in upi_rows:
                vpa = str(row.get("VPA"))
                cur.execute(
                    """
                    INSERT INTO UPIHandle(vpa_raw, vpa_normalized, holder_name_raw, linked_account_id, holder_entity_uid, source_evidence_id, created_at)
                    VALUES (%s, %s, NULL, NULL, NULL, NULL, NOW())
                    RETURNING upi_id
                    """,
                    (vpa, _norm_upi(vpa)),
                )
                upi_id = int(cur.fetchone()[0])
                entity_uid = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO EntityMap(entity_uid, entity_type, pole_subtype, sql_table, sql_pk, status, created_at, updated_at)
                    VALUES (%s, 'Object', 'UPIHandle', 'UPIHandle', %s, 'active', NOW(), NOW())
                    """,
                    (entity_uid, str(upi_id)),
                )
                upi_map[vpa] = (upi_id, entity_uid)
        dst.commit()
        print(f"[migrate] OK    UPIHandle: {len(upi_rows)} rows")
        results.append({"table": "UPIHandle", "status": "ok", "rows": len(upi_rows), "error": None})
    except Exception as exc:
        dst.rollback()
        upi_map.clear()
        print(f"[migrate] FAIL  UPIHandle: {exc}")
        results.append({"table": "UPIHandle", "status": "failed", "rows": 0, "error": str(exc)})

    try:
        with dst.cursor() as cur:
            for row in phone_rows:
                number = str(row.get("Number"))
                cur.execute(
                    """
                    INSERT INTO PhoneNumber(number_raw, number_normalized, holder_name_raw, imei_ref, holder_entity_uid, source_evidence_id, created_at)
                    VALUES (%s, %s, NULL, NULL, NULL, NULL, NOW())
                    RETURNING phone_id
                    """,
                    (number, _norm_phone(number)),
                )
                phone_id = int(cur.fetchone()[0])
                entity_uid = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO EntityMap(entity_uid, entity_type, pole_subtype, sql_table, sql_pk, status, created_at, updated_at)
                    VALUES (%s, 'Object', 'PhoneNumber', 'PhoneNumber', %s, 'active', NOW(), NOW())
                    """,
                    (entity_uid, str(phone_id)),
                )
                phone_map[number] = (phone_id, entity_uid)
        dst.commit()
        print(f"[migrate] OK    PhoneNumber: {len(phone_rows)} rows")
        results.append({"table": "PhoneNumber", "status": "ok", "rows": len(phone_rows), "error": None})
    except Exception as exc:
        dst.rollback()
        phone_map.clear()
        print(f"[migrate] FAIL  PhoneNumber: {exc}")
        results.append({"table": "PhoneNumber", "status": "failed", "rows": 0, "error": str(exc)})

    if not account_map and account_rows:
        print("[migrate] SKIP  Transaction: Account block failed, no account_map to resolve against")
        results.append({"table": "Transaction", "status": "skipped", "rows": 0, "error": "dependency Account failed"})
    else:
        try:
            with dst.cursor() as cur:
                skipped_bad_ts = 0
                inserted = 0
                for row in transaction_rows:
                    # A malformed/missing timestamp used to silently become the
                    # epoch sentinel "1970-01-01T00:00:00Z", corrupting any
                    # time-ordering logic downstream (money-trail layering,
                    # spike detection). Skip-and-report instead, now that
                    # per-block visibility exists to actually see it happen.
                    ts = row.get("Timestamp") or row.get("observed_date")
                    if not ts:
                        skipped_bad_ts += 1
                        continue
                    from_acc = account_map.get(str(row.get("FromAccount")))
                    to_raw = str(row.get("ToAccount") or "")
                    to_acc = account_map.get(to_raw)
                    # A cash-out's ToAccount is a crypto wallet address, which is not
                    # an Account and never resolves against account_map -- previously
                    # those rows landed with to_account_id NULL and the trail simply
                    # stopped, hiding the crypto endpoint entirely.
                    to_wallet = to_raw if (not to_acc and to_raw in wallet_addresses) else None
                    cur.execute(
                        """
                        INSERT INTO Transaction(
                            from_account_id, from_upi_id, to_account_id, to_upi_id, to_wallet_address,
                            amount, txn_timestamp, mode, utr_ref, direction, source_evidence_id, created_at
                        )
                        VALUES (%s, NULL, %s, NULL, %s, %s, %s, %s, %s, %s, NULL, NOW())
                        """,
                        (
                            from_acc[0] if from_acc else None,
                            to_acc[0] if to_acc else None,
                            to_wallet,
                            row.get("Amount") or 0,
                            ts,
                            row.get("Channel"),
                            row.get("TxnID"),
                            row.get("role") or row.get("HopRole"),
                        ),
                    )
                    inserted += 1
            dst.commit()
            note = f" ({skipped_bad_ts} skipped: missing timestamp)" if skipped_bad_ts else ""
            print(f"[migrate] OK    Transaction: {inserted} rows{note}")
            results.append({"table": "Transaction", "status": "ok", "rows": inserted, "error": None})
        except Exception as exc:
            dst.rollback()
            print(f"[migrate] FAIL  Transaction: {exc}")
            results.append({"table": "Transaction", "status": "failed", "rows": 0, "error": str(exc)})

    try:
        with dst.cursor() as cur:
            for row in ir_rows:
                cur.execute(
                    """
                    INSERT INTO InvestigationReport(
                        case_id, accused_id, report_date, findings_narrative, filed_by, status, schema_id_used, created_at
                    )
                    VALUES (%s, NULL, %s, %s, NULL, %s, NULL, NOW())
                    RETURNING report_id
                    """,
                    (
                        row.get("CaseMasterID"),
                        row.get("ReportDate"),
                        row.get("MoneyTrailNotes"),
                        "historical",
                    ),
                )
                # Previously never minted -- historical InvestigationReport rows
                # had no entity_uid at all, so they could never appear as graph
                # nodes (confirmed by tracing through: live ingestion mints this
                # via _ensure_entity, but this migration path never did).
                report_id = int(cur.fetchone()[0])
                entity_uid = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO EntityMap(entity_uid, entity_type, pole_subtype, sql_table, sql_pk, status, created_at, updated_at)
                    VALUES (%s, 'Event', 'InvestigationReport', 'InvestigationReport', %s, 'active', NOW(), NOW())
                    """,
                    (entity_uid, str(report_id)),
                )
        dst.commit()
        print(f"[migrate] OK    InvestigationReport: {len(ir_rows)} rows")
        results.append({"table": "InvestigationReport", "status": "ok", "rows": len(ir_rows), "error": None})
    except Exception as exc:
        dst.rollback()
        print(f"[migrate] FAIL  InvestigationReport: {exc}")
        results.append({"table": "InvestigationReport", "status": "failed", "rows": 0, "error": str(exc)})

    try:
        with dst.cursor() as cur:
            skipped = 0
            updated = 0
            for row in uses_rows:
                # from_person_id is a case-scoped natural key like "P_SCN2_A1" --
                # confirmed against actual data (never the "ACC:"/"COMP:" format
                # _parse_person_ref expected, which matched nothing and skipped
                # every row). Resolved via source_caseid -> that case's Accused row.
                case_id = str(row.get("source_caseid") or "")
                holder_uid = accused_by_case_person.get(case_id)
                if not holder_uid:
                    skipped += 1
                    continue
                object_type = str(row.get("object_type") or "").lower()
                # to_object_id carries the EXT_UPI/EXT_Phone/EXT_Device natural-key
                # prefix ("UPI_imran...@axl", "PHONE_961...", "DEV_351...") but
                # account_map/upi_map/phone_map are keyed by the raw VPA/number/IMEI
                # (accounts have no such prefixed id column) -- confirmed against
                # actual EXT_Uses/EXT_UPI/EXT_Phone/EXT_Device rows, where an
                # unstripped id never matched anything and every row was skipped.
                raw_object_id = str(row.get("to_object_id") or "")
                prefix = {"upi": "UPI_", "phone": "PHONE_", "device": "DEV_"}.get(object_type, "")
                object_id = raw_object_id[len(prefix):] if prefix and raw_object_id.startswith(prefix) else raw_object_id
                if object_type == "account" and object_id in account_map:
                    cur.execute(
                        "UPDATE Account SET holder_entity_uid = COALESCE(holder_entity_uid, %s) WHERE account_id = %s",
                        (holder_uid, account_map[object_id][0]),
                    )
                    updated += 1
                elif object_type == "upi" and object_id in upi_map:
                    cur.execute(
                        "UPDATE UPIHandle SET holder_entity_uid = COALESCE(holder_entity_uid, %s) WHERE upi_id = %s",
                        (holder_uid, upi_map[object_id][0]),
                    )
                    updated += 1
                elif object_type == "phone" and object_id in phone_map:
                    cur.execute(
                        "UPDATE PhoneNumber SET holder_entity_uid = COALESCE(holder_entity_uid, %s) WHERE phone_id = %s",
                        (holder_uid, phone_map[object_id][0]),
                    )
                    updated += 1
                elif object_type == "device" and object_id in device_map:
                    cur.execute(
                        "UPDATE Device SET holder_entity_uid = COALESCE(holder_entity_uid, %s) WHERE device_id = %s",
                        (holder_uid, device_map[object_id][0]),
                    )
                    updated += 1
                else:
                    skipped += 1
        dst.commit()
        print(f"[migrate] OK    EXT_Uses(holder-resolution): {updated} updated, {skipped} skipped")
        results.append({"table": "EXT_Uses(holder-resolution)", "status": "ok", "rows": updated, "error": None})
    except Exception as exc:
        dst.rollback()
        print(f"[migrate] FAIL  EXT_Uses(holder-resolution): {exc}")
        results.append({"table": "EXT_Uses(holder-resolution)", "status": "failed", "rows": 0, "error": str(exc)})

    # EXT_IP/EXT_Wallet are copied verbatim by _load_direct_tables and keep their
    # natural text PKs (IPAddress / Address), but nothing ever minted EntityMap rows
    # for them -- so load_neo4j_from_pg.py had no entity_uid to key a node on and both
    # were silently absent from the graph. Scenario 4's operator co-location (shared IP
    # geolocation = one base) and scenario 3's crypto cash-out endpoint each need them
    # as real nodes. Unlike Account/UPI/Device/Phone they get no first-class table:
    # nothing resolves or dedupes them, so the EXT_ row IS the object.
    for ext_table, pk_col, subtype in [("EXT_IP", "IPAddress", "IP"), ("EXT_Wallet", "Address", "Wallet")]:
        try:
            with dst.cursor() as cur:
                cur.execute(f"SELECT {pk_col} FROM {ext_table}")
                keys = [str(r[0]) for r in cur.fetchall()]
                for key in keys:
                    cur.execute(
                        """
                        INSERT INTO EntityMap(entity_uid, entity_type, pole_subtype, sql_table, sql_pk, status, created_at, updated_at)
                        VALUES (%s, 'Object', %s, %s, %s, 'active', NOW(), NOW())
                        """,
                        (str(uuid.uuid4()), subtype, ext_table, key),
                    )
            dst.commit()
            print(f"[migrate] OK    EntityMap({ext_table}): {len(keys)} rows")
            results.append({"table": f"EntityMap({ext_table})", "status": "ok", "rows": len(keys), "error": None})
        except Exception as exc:
            dst.rollback()
            print(f"[migrate] FAIL  EntityMap({ext_table}): {exc}")
            results.append({"table": f"EntityMap({ext_table})", "status": "failed", "rows": 0, "error": str(exc)})


_UNIQUE_INDEXES = [
    ("idx_device_imei_norm", "Device", "imei_normalized"),
    ("idx_account_number_norm", "Account", "account_number_normalized"),
    ("idx_upi_vpa_norm", "UPIHandle", "vpa_normalized"),
    ("idx_phone_number_norm", "PhoneNumber", "number_normalized"),
]


def _upgrade_unique_indexes(dst: psycopg.Connection, results: list[dict[str, Any]]) -> None:
    """Upgrade the four normalized-identifier indexes to UNIQUE, now that the reload's
    dedup pass (SELECT-then-INSERT in _write_object_row) guarantees no duplicates.

    Must run AFTER the data reload, never as part of schema_pg.sql: that file is applied
    BEFORE Account/UPIHandle/PhoneNumber/Device are deleted and reloaded, so creating
    these UNIQUE against a database with any pre-existing duplicate (e.g. leftover
    partial demo runs from before this constraint existed) would fail schema application
    entirely and leave the whole migration unable to even start.
    """
    for index_name, table, column in _UNIQUE_INDEXES:
        try:
            with dst.cursor() as cur:
                # DROP + CREATE UNIQUE rather than a bare CREATE UNIQUE INDEX IF NOT
                # EXISTS: an index with this name already exists (as plain, non-unique)
                # from schema_pg.sql, and IF NOT EXISTS would see the name taken and
                # silently skip -- leaving the constraint unenforced.
                cur.execute(f"DROP INDEX IF EXISTS {index_name}")
                cur.execute(f"CREATE UNIQUE INDEX {index_name} ON {table}({column})")
            dst.commit()
            print(f"[migrate] OK    {index_name}: upgraded to UNIQUE")
            results.append({"table": index_name, "status": "ok", "rows": 0, "error": None})
        except Exception as exc:
            dst.rollback()
            # Not fatal to the whole migration: the deterministic join still works via
            # app-level SELECT-then-INSERT, this only removes the loud-failure backstop
            # for a genuine duplicate (which this print calls out for manual cleanup).
            print(f"[migrate] FAIL  {index_name}: {exc} -- a duplicate {column} likely "
                  f"survived the reload; find it with "
                  f"SELECT {column}, count(*) FROM {table} GROUP BY {column} HAVING count(*)>1")
            results.append({"table": index_name, "status": "failed", "rows": 0, "error": str(exc)})


def main() -> int:
    # Must run before argparse's default=os.getenv(...) below evaluates --
    # previously load_dotenv() ran *after* parser.add_argument(), so a
    # standalone `python migrate_sqlite_to_pg.py` run never actually saw
    # .env's DB_NAME and silently fell back to the hardcoded "ksp_crime".
    load_dotenv(ROOT / ".env")

    live_db_name = os.getenv("DB_NAME", "postgres")

    parser = argparse.ArgumentParser(description="Migrate historical SQLite seed to PostgreSQL schema.")
    parser.add_argument("--sqlite-path", default=str(SQLITE_PATH_DEFAULT))
    # Default to whatever the live app actually reads (DB_NAME), not a
    # separate TARGET_DB_NAME nobody sets -- confirmed live this repo's .env
    # sets DB_NAME=postgres while the old default here was "ksp_crime", so a
    # migration run under the documented command would populate a database
    # the running app never queries. TARGET_DB_NAME remains as an explicit
    # opt-in for anyone who really wants a separate scratch database.
    parser.add_argument("--target-db", default=os.getenv("TARGET_DB_NAME", live_db_name))
    parser.add_argument("--maintenance-db", default=live_db_name)
    parser.add_argument("--skip-schema", action="store_true")
    parser.add_argument("--skip-seed", action="store_true")
    args = parser.parse_args()

    if args.target_db != live_db_name:
        print(
            f"[migrate] WARNING: --target-db={args.target_db!r} but the live app reads DB_NAME={live_db_name!r} "
            f"(from .env) -- data migrated to {args.target_db!r} will NOT be visible to the running app "
            f"unless DB_NAME is changed to match. Proceeding anyway since --target-db was explicit."
        )

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        from data_generation.db_loader import build_db

        build_db(
            sql_dir=str(ROOT / "sample_data" / "historical" / "sql"),
            db_path=str(sqlite_path),
            schema_path=str(ROOT / "sample_data" / "historical" / "db" / "schema.sql"),
        )
        print(f"[migrate] Built missing SQLite DB: {sqlite_path}")

    _ensure_target_database(target_db=args.target_db, maintenance_db=args.maintenance_db)

    results: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as src_conn:
        src_conn.row_factory = sqlite3.Row
        with psycopg.connect(_build_conninfo(args.target_db), prepare_threshold=None) as dst_conn:
            if not args.skip_schema:
                _apply_sql_file(dst_conn, SCHEMA_SQL_PATH)
                _apply_sql_file(dst_conn, DEMO_SCENARIO_SQL_PATH)
                _apply_sql_file(dst_conn, ASSISTANT_SQL_PATH)
            if not args.skip_seed:
                _apply_sql_file(dst_conn, SEED_SQL_PATH)

            _load_direct_tables(src_conn, dst_conn, results)
            _migrate_transformed_tables(src_conn, dst_conn, results)
            # Account/UPIHandle/PhoneNumber/Device are always deleted+reloaded by the two
            # calls above (unconditional on --skip-schema/--skip-seed), so the data is
            # guaranteed deduped by the time this runs.
            _upgrade_unique_indexes(dst_conn, results)

    failed = [r for r in results if r["status"] == "failed"]
    skipped = [r for r in results if r["status"] == "skipped"]
    print("\n[migrate] ==== Summary ====")
    for r in results:
        marker = {"ok": "OK    ", "failed": "FAILED", "skipped": "SKIP  "}[r["status"]]
        detail = f" -- {r['error']}" if r["error"] else ""
        print(f"[migrate]   {marker} {r['table']}: {r['rows']} rows{detail}")
    print(f"[migrate] {len(results) - len(failed) - len(skipped)}/{len(results)} tables OK"
          f"{f', {len(skipped)} skipped' if skipped else ''}{f', {len(failed)} FAILED' if failed else ''}.")

    if failed:
        print("[migrate] Completed with failures -- see FAILED rows above.")
        return 1
    print("[migrate] Completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

