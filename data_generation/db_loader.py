"""
db_loader.py - Build output/historical/db/ksp.sqlite from schema.sql,
then bulk-load all KSP-core + extension CSVs.

PRAGMA foreign_keys = ON throughout; any FK violation causes immediate abort.

Run:
    python db_loader.py                      # default paths
    python db_loader.py --sql-dir output/historical/sql --db output/historical/db/ksp.sqlite
"""
from __future__ import annotations
import argparse
import csv
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("db_loader")

DEFAULT_SQL_DIR = "output/historical/sql"
DEFAULT_DB_PATH = "output/historical/db/ksp.sqlite"
DEFAULT_SCHEMA   = "output/historical/db/schema.sql"


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        log.warning(f"CSV not found, skipping: {path}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _bulk_insert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    col_str = ", ".join(cols)
    sql = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({placeholders})"
    values = []
    for r in rows:
        row_vals = []
        for c in cols:
            v = r.get(c, "")
            # Empty strings should load as NULL for FK columns.
            if v == "":
                v = None
            row_vals.append(v)
        values.append(row_vals)
    conn.executemany(sql, values)
    return len(rows)


def build_db(sql_dir: str = DEFAULT_SQL_DIR,
             db_path: str = DEFAULT_DB_PATH,
             schema_path: str = DEFAULT_SCHEMA) -> str:
    """
    Create/replace ksp.sqlite, apply schema.sql, and load all CSVs.
    Raises on any FK violation.
    Returns path to the database.
    """
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # Remove stale DB if present
    if db_file.exists():
        db_file.unlink()
        log.info(f"Removed existing DB: {db_file}")

    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    # Apply schema
    schema_file = Path(schema_path)
    if not schema_file.exists():
        raise FileNotFoundError(f"schema.sql not found: {schema_file}")
    schema_sql = schema_file.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()
    log.info(f"Schema applied from {schema_file}")

    sql = Path(sql_dir)
    ksp = sql / "ksp"
    master = ksp / "master"
    ext = sql / "extension"

    def load(table: str, csv_path: Path, count_log: bool = True) -> int:
        rows = _load_csv(csv_path)
        n = _bulk_insert(conn, table, rows)
        if count_log and n:
            log.info(f"  {table}: {n} rows")
        return n

    # -----------------------------------------------------------------------
    # Load order: masters first (no FKs to case tables), then core, then ext
    # -----------------------------------------------------------------------
    log.info("Loading master tables...")
    load("State",           master / "State.csv")
    load("District",        master / "District.csv")
    load("UnitType",        master / "UnitType.csv")
    load("Unit",            master / "Unit.csv")
    load("Rank",            master / "Rank.csv")
    load("Designation",     master / "Designation.csv")
    load("Employee",        master / "Employee.csv")
    load("Court",           master / "Court.csv")
    load("CaseCategory",    master / "CaseCategory.csv")
    load("GravityOffence",  master / "GravityOffence.csv")
    load("CaseStatusMaster",master / "CaseStatusMaster.csv")
    load("CrimeHead",       master / "CrimeHead.csv")
    load("CrimeSubHead",    master / "CrimeSubHead.csv")
    load("Act",             master / "Act.csv")
    load("Section",         master / "Section.csv")
    load("CrimeHeadActSection", master / "CrimeHeadActSection.csv")
    load("CasteMaster",     master / "CasteMaster.csv")
    load("ReligionMaster",  master / "ReligionMaster.csv")
    load("OccupationMaster",master / "OccupationMaster.csv")
    conn.commit()

    log.info("Loading KSP-core case tables...")
    load("CaseMaster",          ksp / "CaseMaster.csv")
    load("ComplainantDetails",  ksp / "ComplainantDetails.csv")
    load("Victim",              ksp / "Victim.csv")
    load("Accused",             ksp / "Accused.csv")
    load("ArrestSurrender",     ksp / "ArrestSurrender.csv")
    load("ActSectionAssociation", ksp / "ActSectionAssociation.csv")
    load("ChargesheetDetails",  ksp / "ChargesheetDetails.csv")
    conn.commit()

    log.info("Loading extension tables...")
    load("EXT_Account",     ext / "accounts.csv")
    load("EXT_Phone",       ext / "phones.csv")
    load("EXT_Device",      ext / "devices.csv")
    load("EXT_UPI",         ext / "upis.csv")
    load("EXT_IP",          ext / "ips.csv")
    load("EXT_Wallet",      ext / "wallets.csv")
    load("EXT_Transaction",          ext / "transactions.csv")
    load("EXT_Uses",                 ext / "rels_uses.csv")
    load("EXT_Mentions",             ext / "rels_mentions.csv")
    load("EXT_AccusedIn",            ext / "rels_accused_in.csv")
    load("EXT_ComplainantIn",        ext / "rels_complainant_in.csv")
    load("EXT_CaseGeo",              ext / "case_geo.csv")
    load("EXT_InvestigationReport",  ext / "investigation_reports.csv")
    load("EXT_VictimDetail",         ext / "victim_details.csv")
    load("EXT_AccusedDetail",        ext / "accused_details.csv")
    load("EXT_SubEvent",             ext / "sub_events.csv")
    load("EXT_LegalElement",         ext / "legal_elements.csv")
    load("EXT_EvidenceType",         ext / "evidence_types.csv")
    load("EXT_Precedent",            ext / "precedents.csv")
    load("EXT_IPCSection",           ext / "ipc_sections.csv")
    conn.commit()

    # -----------------------------------------------------------------------
    # Foreign-key integrity check — fail loudly on any violation
    # -----------------------------------------------------------------------
    log.info("Running PRAGMA foreign_key_check...")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        msg = "\n".join(str(v) for v in violations[:20])
        conn.close()
        raise RuntimeError(f"FK violations found:\n{msg}")
    log.info("FK check PASSED — zero violations.")

    # Row counts summary
    log.info("Row counts:")
    for table in [
        "CaseMaster","ComplainantDetails","Victim","Accused",
        "ArrestSurrender","ActSectionAssociation","ChargesheetDetails",
        "EXT_Account","EXT_Transaction","EXT_Uses","EXT_Mentions",
        "EXT_AccusedIn","EXT_ComplainantIn","EXT_VictimDetail",
        "EXT_AccusedDetail","EXT_SubEvent",
    ]:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            log.info(f"  {table}: {n}")
        except Exception:
            pass

    conn.close()
    log.info(f"ksp.sqlite built successfully: {db_file}")
    return str(db_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load KSP CSVs into SQLite")
    parser.add_argument("--sql-dir", default=DEFAULT_SQL_DIR)
    parser.add_argument("--db",      default=DEFAULT_DB_PATH)
    parser.add_argument("--schema",  default=DEFAULT_SCHEMA)
    args = parser.parse_args()
    try:
        build_db(args.sql_dir, args.db, args.schema)
    except Exception as e:
        log.error(str(e))
        sys.exit(1)
