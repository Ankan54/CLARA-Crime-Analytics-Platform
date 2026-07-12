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
    with psycopg.connect(_build_conninfo(maintenance_db), autocommit=True) as conn:
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


def _parse_person_ref(person_ref: str) -> tuple[str, str] | None:
    person_ref = person_ref.strip()
    if person_ref.startswith("ACC:"):
        return "Accused", person_ref.split(":", 1)[1]
    if person_ref.startswith("COMP:"):
        return "ComplainantDetails", person_ref.split(":", 1)[1]
    return None


def _load_direct_tables(src: sqlite3.Connection, dst: psycopg.Connection) -> None:
    with dst.cursor() as cur:
        for table in MASTER_TABLES + CORE_TABLES + KEPT_EXT_TABLES:
            _delete_table(cur, table)
            rows = _sqlite_rows(src, table)
            _insert_rows(cur, table, rows)
            print(f"[migrate] Copied {table}: {len(rows)} rows")
    dst.commit()


def _migrate_transformed_tables(src: sqlite3.Connection, dst: psycopg.Connection) -> None:
    account_rows = _sqlite_rows(src, "EXT_Account")
    upi_rows = _sqlite_rows(src, "EXT_UPI")
    phone_rows = _sqlite_rows(src, "EXT_Phone")
    device_rows = _sqlite_rows(src, "EXT_Device")
    transaction_rows = _sqlite_rows(src, "EXT_Transaction")
    uses_rows = _sqlite_rows(src, "EXT_Uses")
    ir_rows = _sqlite_rows(src, "EXT_InvestigationReport")

    account_case_map: dict[str, int] = {}
    for row in _sqlite_rows(src, "EXT_Mentions"):
        if (row.get("object_type") or "").lower() == "account" and row.get("object_id") and row.get("case_master_id"):
            account_case_map.setdefault(str(row["object_id"]), int(row["case_master_id"]))
    for row in transaction_rows:
        case_id = row.get("CaseMasterID")
        if case_id:
            if row.get("FromAccount"):
                account_case_map.setdefault(str(row["FromAccount"]), int(case_id))
            if row.get("ToAccount"):
                account_case_map.setdefault(str(row["ToAccount"]), int(case_id))

    with dst.cursor() as cur:
        for table in ["ReviewQueueItem", "Transaction", "PhoneNumber", "UPIHandle", "Account", "Device", "InvestigationReport", "EntityMap"]:
            _delete_table(cur, table)

        entity_map_by_ref: dict[tuple[str, str], str] = {}
        for person_table, pk_col, pole_subtype in [
            ("Accused", "AccusedMasterID", "Accused"),
            ("ComplainantDetails", "ComplainantID", "Complainant"),
            ("Victim", "VictimMasterID", "Victim"),
        ]:
            rows = _sqlite_rows(src, person_table)
            for row in rows:
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

        device_map: dict[str, tuple[int, str]] = {}
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

        account_map: dict[str, tuple[int, str]] = {}
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

        upi_map: dict[str, tuple[int, str]] = {}
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

        phone_map: dict[str, tuple[int, str]] = {}
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

        for row in transaction_rows:
            from_acc = account_map.get(str(row.get("FromAccount")))
            to_acc = account_map.get(str(row.get("ToAccount")))
            cur.execute(
                """
                INSERT INTO Transaction(
                    from_account_id, from_upi_id, to_account_id, to_upi_id, amount, txn_timestamp,
                    mode, utr_ref, direction, source_evidence_id, created_at
                )
                VALUES (%s, NULL, %s, NULL, %s, %s, %s, %s, %s, NULL, NOW())
                """,
                (
                    from_acc[0] if from_acc else None,
                    to_acc[0] if to_acc else None,
                    row.get("Amount") or 0,
                    row.get("Timestamp") or row.get("observed_date") or "1970-01-01T00:00:00Z",
                    row.get("Channel"),
                    row.get("TxnID"),
                    row.get("role") or row.get("HopRole"),
                ),
            )

        for row in ir_rows:
            cur.execute(
                """
                INSERT INTO InvestigationReport(
                    case_id, accused_id, report_date, findings_narrative, filed_by, status, schema_id_used, created_at
                )
                VALUES (%s, NULL, %s, %s, NULL, %s, NULL, NOW())
                """,
                (
                    row.get("CaseMasterID"),
                    row.get("ReportDate"),
                    row.get("MoneyTrailNotes"),
                    "historical",
                ),
            )

        for row in uses_rows:
            person_ref = str(row.get("from_person_id") or "")
            parsed = _parse_person_ref(person_ref)
            if not parsed:
                continue
            person_table, person_pk = parsed
            holder_uid = entity_map_by_ref.get((person_table, person_pk))
            if not holder_uid:
                continue
            object_type = str(row.get("object_type") or "").lower()
            object_id = str(row.get("to_object_id") or "")
            if object_type == "account" and object_id in account_map:
                cur.execute(
                    "UPDATE Account SET holder_entity_uid = COALESCE(holder_entity_uid, %s) WHERE account_id = %s",
                    (holder_uid, account_map[object_id][0]),
                )
            elif object_type == "upi" and object_id in upi_map:
                cur.execute(
                    "UPDATE UPIHandle SET holder_entity_uid = COALESCE(holder_entity_uid, %s) WHERE upi_id = %s",
                    (holder_uid, upi_map[object_id][0]),
                )
            elif object_type == "phone" and object_id in phone_map:
                cur.execute(
                    "UPDATE PhoneNumber SET holder_entity_uid = COALESCE(holder_entity_uid, %s) WHERE phone_id = %s",
                    (holder_uid, phone_map[object_id][0]),
                )

    dst.commit()
    print("[migrate] Transformed EXT_Account/UPI/Phone/Device/Transaction and minted EntityMap rows.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate historical SQLite seed to PostgreSQL schema.")
    parser.add_argument("--sqlite-path", default=str(SQLITE_PATH_DEFAULT))
    parser.add_argument("--target-db", default=os.getenv("TARGET_DB_NAME", "ksp_crime"))
    parser.add_argument("--maintenance-db", default=os.getenv("DB_NAME", "postgres"))
    parser.add_argument("--skip-schema", action="store_true")
    parser.add_argument("--skip-seed", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

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

    with sqlite3.connect(sqlite_path) as src_conn:
        src_conn.row_factory = sqlite3.Row
        with psycopg.connect(_build_conninfo(args.target_db)) as dst_conn:
            if not args.skip_schema:
                _apply_sql_file(dst_conn, SCHEMA_SQL_PATH)
            if not args.skip_seed:
                _apply_sql_file(dst_conn, SEED_SQL_PATH)

            _load_direct_tables(src_conn, dst_conn)
            _migrate_transformed_tables(src_conn, dst_conn)

    print("[migrate] Completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

