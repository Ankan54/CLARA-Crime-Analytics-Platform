"""
pg_store.py — Drop/recreate all tables in AWS RDS Postgres and bulk-load
              historical CSVs in FK-safe order.

Checkpoint: .ingest_checkpoints/pg_checkpoint.json
    {table_name: "done"} — tables already loaded; skipped on resume.

Wipe: drops all tables (CASCADE) and clears the checkpoint before reloading.

Usage (standalone):
    python -m data_ingestion.pg_store
    python -m data_ingestion.pg_store --no-wipe   # skip drop, resume from checkpoint
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from . import config as cfg

# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------
_CHECKPOINT = cfg.STATE_DIR / "pg_checkpoint.json"


def _load_checkpoint() -> dict[str, str]:
    if _CHECKPOINT.exists():
        return json.loads(_CHECKPOINT.read_text(encoding="utf-8"))
    return {}


def _save_checkpoint(state: dict[str, str]) -> None:
    cfg.STATE_DIR.mkdir(parents=True, exist_ok=True)
    _CHECKPOINT.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def _connect():
    import psycopg2

    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode=os.environ.get("DB_SSL", "require"),
        connect_timeout=15,
    )


# ---------------------------------------------------------------------------
# Schema — Postgres DDL (translated from schema.sql; PRAGMA removed)
# ---------------------------------------------------------------------------
_SCHEMA_SQL = """
-- KSP Crime Intelligence Platform — Postgres schema
-- Translated from SQLite schema.sql: PRAGMA removed, INTEGER PRIMARY KEY -> SERIAL
-- TEXT/INTEGER PRIMARY KEY columns kept as explicit PKs (no auto-increment needed for them)

CREATE TABLE IF NOT EXISTS State (
    StateID   INTEGER PRIMARY KEY,
    StateName TEXT    NOT NULL,
    Active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS District (
    DistrictID   INTEGER PRIMARY KEY,
    DistrictName TEXT    NOT NULL,
    StateID      INTEGER NOT NULL REFERENCES State(StateID),
    Active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS UnitType (
    UnitTypeID    INTEGER PRIMARY KEY,
    UnitTypeName  TEXT    NOT NULL,
    CityDistState TEXT,
    Hierarchy     INTEGER,
    Active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Unit (
    UnitID        INTEGER PRIMARY KEY,
    UnitName      TEXT    NOT NULL,
    TypeID        INTEGER NOT NULL REFERENCES UnitType(UnitTypeID),
    ParentUnit    INTEGER REFERENCES Unit(UnitID),
    NationalityID INTEGER,
    StateID       INTEGER NOT NULL REFERENCES State(StateID),
    DistrictID    INTEGER NOT NULL REFERENCES District(DistrictID),
    Active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Rank (
    RankID    INTEGER PRIMARY KEY,
    RankName  TEXT    NOT NULL,
    Hierarchy INTEGER,
    Active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Designation (
    DesignationID   INTEGER PRIMARY KEY,
    DesignationName TEXT    NOT NULL,
    Active          INTEGER NOT NULL DEFAULT 1,
    SortOrder       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS Employee (
    EmployeeID           INTEGER PRIMARY KEY,
    DistrictID           INTEGER NOT NULL REFERENCES District(DistrictID),
    UnitID               INTEGER NOT NULL REFERENCES Unit(UnitID),
    RankID               INTEGER NOT NULL REFERENCES Rank(RankID),
    DesignationID        INTEGER NOT NULL REFERENCES Designation(DesignationID),
    KGID                 TEXT,
    FirstName            TEXT    NOT NULL,
    EmployeeDOB          TEXT,
    GenderID             INTEGER,
    BloodGroupID         INTEGER,
    PhysicallyChallenged INTEGER DEFAULT 0,
    AppointmentDate      TEXT
);

CREATE TABLE IF NOT EXISTS Court (
    CourtID    INTEGER PRIMARY KEY,
    CourtName  TEXT    NOT NULL,
    DistrictID INTEGER NOT NULL REFERENCES District(DistrictID),
    StateID    INTEGER NOT NULL REFERENCES State(StateID),
    Active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS CaseCategory (
    CaseCategoryID INTEGER PRIMARY KEY,
    LookupValue    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS GravityOffence (
    GravityOffenceID INTEGER PRIMARY KEY,
    LookupValue      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS CaseStatusMaster (
    CaseStatusID   INTEGER PRIMARY KEY,
    CaseStatusName TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS CrimeHead (
    CrimeHeadID    INTEGER PRIMARY KEY,
    CrimeGroupName TEXT    NOT NULL,
    Active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS CrimeSubHead (
    CrimeSubHeadID INTEGER PRIMARY KEY,
    CrimeHeadID    INTEGER NOT NULL REFERENCES CrimeHead(CrimeHeadID),
    CrimeHeadName  TEXT    NOT NULL,
    SeqID          INTEGER DEFAULT 0,
    Active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Act (
    ActCode        TEXT PRIMARY KEY,
    ActDescription TEXT NOT NULL,
    ShortName      TEXT,
    Active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Section (
    ActCode            TEXT NOT NULL REFERENCES Act(ActCode),
    SectionCode        TEXT NOT NULL,
    SectionDescription TEXT NOT NULL,
    Active             INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (ActCode, SectionCode)
);

CREATE TABLE IF NOT EXISTS CrimeHeadActSection (
    CrimeHeadID  INTEGER NOT NULL REFERENCES CrimeHead(CrimeHeadID),
    ActCode      TEXT    NOT NULL REFERENCES Act(ActCode),
    SectionCode  TEXT    NOT NULL,
    PRIMARY KEY (CrimeHeadID, ActCode, SectionCode),
    FOREIGN KEY (ActCode, SectionCode) REFERENCES Section(ActCode, SectionCode)
);

CREATE TABLE IF NOT EXISTS CasteMaster (
    caste_master_id   INTEGER PRIMARY KEY,
    caste_master_name TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS ReligionMaster (
    ReligionID   INTEGER PRIMARY KEY,
    ReligionName TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS OccupationMaster (
    OccupationID   INTEGER PRIMARY KEY,
    OccupationName TEXT    NOT NULL
);

-- KSP core case tables

CREATE TABLE IF NOT EXISTS CaseMaster (
    CaseMasterID        INTEGER PRIMARY KEY,
    CrimeNo             TEXT    NOT NULL UNIQUE,
    CaseNo              TEXT    NOT NULL,
    CrimeRegisteredDate TEXT    NOT NULL,
    PolicePersonID      INTEGER NOT NULL REFERENCES Employee(EmployeeID),
    PoliceStationID     INTEGER NOT NULL REFERENCES Unit(UnitID),
    CaseCategoryID      INTEGER NOT NULL REFERENCES CaseCategory(CaseCategoryID),
    GravityOffenceID    INTEGER NOT NULL REFERENCES GravityOffence(GravityOffenceID),
    CrimeMajorHeadID    INTEGER NOT NULL REFERENCES CrimeHead(CrimeHeadID),
    CrimeMinorHeadID    INTEGER NOT NULL REFERENCES CrimeSubHead(CrimeSubHeadID),
    CaseStatusID        INTEGER NOT NULL REFERENCES CaseStatusMaster(CaseStatusID),
    CourtID             INTEGER NOT NULL REFERENCES Court(CourtID),
    IncidentFromDate    TEXT,
    IncidentToDate      TEXT,
    InfoReceivedPSDate  TEXT,
    Latitude            DOUBLE PRECISION,
    Longitude           DOUBLE PRECISION,
    BriefFacts          TEXT
);

CREATE TABLE IF NOT EXISTS ComplainantDetails (
    ComplainantID   INTEGER PRIMARY KEY,
    CaseMasterID    INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    ComplainantName TEXT    NOT NULL,
    AgeYear         INTEGER,
    GenderID        TEXT,
    OccupationID    INTEGER REFERENCES OccupationMaster(OccupationID),
    CasteID         INTEGER REFERENCES CasteMaster(caste_master_id),
    ReligionID      INTEGER REFERENCES ReligionMaster(ReligionID),
    Address         TEXT
);

CREATE TABLE IF NOT EXISTS Victim (
    VictimMasterID INTEGER PRIMARY KEY,
    CaseMasterID   INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    VictimName     TEXT    NOT NULL,
    AgeYear        INTEGER,
    GenderID       TEXT,
    VictimPolice   INTEGER REFERENCES Employee(EmployeeID)
);

CREATE TABLE IF NOT EXISTS Accused (
    AccusedMasterID INTEGER PRIMARY KEY,
    CaseMasterID    INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    PersonID        TEXT,
    AccusedName     TEXT    NOT NULL,
    AgeYear         INTEGER,
    GenderID        TEXT
);

CREATE TABLE IF NOT EXISTS ArrestSurrender (
    ArrestSurrenderID         INTEGER PRIMARY KEY,
    CaseMasterID              INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    ArrestSurrenderTypeID     INTEGER,
    ArrestSurrenderDate       TEXT,
    ArrestSurrenderStateId    INTEGER REFERENCES State(StateID),
    ArrestSurrenderDistrictId INTEGER REFERENCES District(DistrictID),
    PoliceStationID           INTEGER REFERENCES Unit(UnitID),
    IOID                      INTEGER REFERENCES Employee(EmployeeID),
    CourtID                   INTEGER REFERENCES Court(CourtID),
    AccusedMasterID           INTEGER NOT NULL REFERENCES Accused(AccusedMasterID),
    IsAccused                 INTEGER DEFAULT 1,
    IsComplainantAccused      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ActSectionAssociation (
    CaseMasterID  INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    ActCode       TEXT    NOT NULL,
    SectionCode   TEXT    NOT NULL,
    ActOrderID    INTEGER DEFAULT 1,
    SectionOrderID INTEGER DEFAULT 1,
    PRIMARY KEY (CaseMasterID, ActCode, SectionCode),
    FOREIGN KEY (ActCode, SectionCode) REFERENCES Section(ActCode, SectionCode)
);

CREATE TABLE IF NOT EXISTS ChargesheetDetails (
    CSID           INTEGER PRIMARY KEY,
    CaseMasterID   INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    CSDate         TEXT,
    CSType         TEXT    NOT NULL DEFAULT 'C',
    PolicePersonID INTEGER REFERENCES Employee(EmployeeID)
);

-- Extension tables

CREATE TABLE IF NOT EXISTS EXT_Account (
    AccountNo      TEXT    PRIMARY KEY,
    Bank           TEXT,
    IFSC           TEXT,
    BranchDistrict TEXT,
    AccountType    TEXT    DEFAULT 'Savings',
    OpenDate       TEXT,
    KYCName        TEXT,
    IsFlaggedMule  INTEGER DEFAULT 0,
    LastInbound    TEXT,
    LastOutbound   TEXT
);

CREATE TABLE IF NOT EXISTS EXT_Phone (
    Number   TEXT PRIMARY KEY,
    PhoneID  TEXT
);

CREATE TABLE IF NOT EXISTS EXT_Device (
    IMEI     TEXT PRIMARY KEY,
    DeviceID TEXT
);

CREATE TABLE IF NOT EXISTS EXT_UPI (
    VPA    TEXT PRIMARY KEY,
    UPIID  TEXT
);

CREATE TABLE IF NOT EXISTS EXT_IP (
    IPAddress TEXT PRIMARY KEY,
    IPID      TEXT,
    GeoLat    DOUBLE PRECISION,
    GeoLong   DOUBLE PRECISION,
    GeoCity   TEXT
);

CREATE TABLE IF NOT EXISTS EXT_Wallet (
    Address   TEXT PRIMARY KEY,
    WalletID  TEXT,
    Chain     TEXT DEFAULT 'USDT'
);

CREATE TABLE IF NOT EXISTS EXT_Transaction (
    TxnID        TEXT PRIMARY KEY,
    FromAccount  TEXT,
    ToAccount    TEXT,
    Amount       INTEGER,
    Timestamp    TEXT,
    Channel      TEXT,
    HopRole      TEXT,
    CaseMasterID INTEGER REFERENCES CaseMaster(CaseMasterID),
    source_caseid  INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date  TEXT,
    confidence     DOUBLE PRECISION DEFAULT 1.0,
    role           TEXT
);

CREATE TABLE IF NOT EXISTS EXT_Uses (
    from_person_id TEXT,
    to_object_id   TEXT,
    object_type    TEXT,
    source_caseid  INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date  TEXT,
    confidence     DOUBLE PRECISION DEFAULT 1.0,
    role           TEXT,
    PRIMARY KEY (from_person_id, to_object_id, object_type)
);

CREATE TABLE IF NOT EXISTS EXT_Mentions (
    case_master_id INTEGER REFERENCES CaseMaster(CaseMasterID),
    object_id      TEXT,
    object_type    TEXT,
    source_caseid  INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date  TEXT,
    confidence     DOUBLE PRECISION DEFAULT 1.0,
    PRIMARY KEY (case_master_id, object_id, object_type)
);

CREATE TABLE IF NOT EXISTS EXT_AccusedIn (
    AccusedMasterID INTEGER REFERENCES Accused(AccusedMasterID),
    CaseMasterID    INTEGER REFERENCES CaseMaster(CaseMasterID),
    source_caseid   INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date   TEXT,
    confidence      DOUBLE PRECISION DEFAULT 1.0,
    role            TEXT,
    PRIMARY KEY (AccusedMasterID, CaseMasterID)
);

CREATE TABLE IF NOT EXISTS EXT_ComplainantIn (
    ComplainantID INTEGER REFERENCES ComplainantDetails(ComplainantID),
    CaseMasterID  INTEGER REFERENCES CaseMaster(CaseMasterID),
    source_caseid INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date TEXT,
    confidence    DOUBLE PRECISION DEFAULT 1.0,
    PRIMARY KEY (ComplainantID, CaseMasterID)
);

CREATE TABLE IF NOT EXISTS EXT_CaseGeo (
    GeoID            INTEGER PRIMARY KEY,
    CaseMasterID     INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    Pincode          TEXT,
    IncidentDistrict TEXT
);

CREATE TABLE IF NOT EXISTS EXT_InvestigationReport (
    ReportID           INTEGER PRIMARY KEY,
    CaseMasterID       INTEGER NOT NULL REFERENCES CaseMaster(CaseMasterID),
    ReportDate         TEXT,
    IOOfficer          TEXT,
    MoneyTrailNotes    TEXT,
    LinkedIdentifiers  TEXT,
    SeizedItems        TEXT,
    Arrests            TEXT,
    IsLive             INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS EXT_VictimDetail (
    VictimMasterID    INTEGER PRIMARY KEY REFERENCES Victim(VictimMasterID),
    OccupationID      INTEGER REFERENCES OccupationMaster(OccupationID),
    CasteID           INTEGER REFERENCES CasteMaster(caste_master_id),
    ReligionID        INTEGER REFERENCES ReligionMaster(ReligionID),
    Address           TEXT,
    Mobile            TEXT,
    LossAmount        INTEGER DEFAULT 0,
    ResidenceDistrict TEXT
);

CREATE TABLE IF NOT EXISTS EXT_AccusedDetail (
    AccusedMasterID   INTEGER PRIMARY KEY REFERENCES Accused(AccusedMasterID),
    OccupationID      INTEGER REFERENCES OccupationMaster(OccupationID),
    CasteID           INTEGER REFERENCES CasteMaster(caste_master_id),
    ReligionID        INTEGER REFERENCES ReligionMaster(ReligionID),
    Address           TEXT,
    IsArrested        INTEGER DEFAULT 0,
    ResidenceDistrict TEXT
);

CREATE TABLE IF NOT EXISTS EXT_SubEvent (
    SubEventID    INTEGER PRIMARY KEY,
    CaseMasterID  INTEGER REFERENCES CaseMaster(CaseMasterID),
    Label         TEXT,
    Timestamp     TEXT,
    source_caseid INTEGER REFERENCES CaseMaster(CaseMasterID),
    observed_date TEXT,
    confidence    DOUBLE PRECISION DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS EXT_LegalElement (
    ElementID   TEXT PRIMARY KEY,
    SectionID   TEXT,
    Name        TEXT,
    Description TEXT
);

CREATE TABLE IF NOT EXISTS EXT_EvidenceType (
    EvidenceTypeID         TEXT PRIMARY KEY,
    Name                   TEXT,
    Description            TEXT,
    Requires63Certificate  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS EXT_Precedent (
    PrecedentID    TEXT PRIMARY KEY,
    CaseName       TEXT,
    Citation       TEXT,
    Year           INTEGER,
    Court          TEXT,
    Outcome        TEXT,
    ElementTurnedOn TEXT,
    SectionID      TEXT,
    HoldingSummary TEXT,
    IsOverruled    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS EXT_IPCSection (
    IPCSectionID  TEXT PRIMARY KEY,
    SectionNumber TEXT,
    Title         TEXT
);
"""

# ---------------------------------------------------------------------------
# Tables to drop (reverse FK order) for clean wipe
# ---------------------------------------------------------------------------
_DROP_ORDER = [
    "EXT_SubEvent", "EXT_AccusedDetail", "EXT_VictimDetail",
    "EXT_InvestigationReport", "EXT_CaseGeo", "EXT_ComplainantIn",
    "EXT_AccusedIn", "EXT_Mentions", "EXT_Uses", "EXT_Transaction",
    "EXT_Wallet", "EXT_IP", "EXT_UPI", "EXT_Device", "EXT_Phone",
    "EXT_Account", "EXT_IPCSection", "EXT_Precedent", "EXT_EvidenceType",
    "EXT_LegalElement",
    "ChargesheetDetails", "ActSectionAssociation", "ArrestSurrender",
    "Accused", "Victim", "ComplainantDetails", "CaseMaster",
    "CrimeHeadActSection", "Section", "Act",
    "OccupationMaster", "ReligionMaster", "CasteMaster",
    "CrimeSubHead", "CrimeHead",
    "CaseStatusMaster", "GravityOffence", "CaseCategory",
    "Court", "Employee", "Designation", "Rank", "Unit", "UnitType",
    "District", "State",
]


# ---------------------------------------------------------------------------
# CSV loading helpers
# ---------------------------------------------------------------------------
def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _coerce(v: str) -> Any:
    """Empty string -> None; else leave as string (psycopg2 handles types)."""
    return None if v == "" else v


def _bulk_insert(cur, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    col_str = ", ".join(cols)
    placeholders = ", ".join("%s" for _ in cols)
    sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    values = [tuple(_coerce(r.get(c, "")) for c in cols) for r in rows]
    cur.executemany(sql, values)
    return len(rows)


# ---------------------------------------------------------------------------
# Wipe
# ---------------------------------------------------------------------------
def _wipe(conn) -> None:
    print("[pg_store] Dropping all tables …", flush=True)
    cur = conn.cursor()
    for table in _DROP_ORDER:
        cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    conn.commit()
    cur.close()
    print("[pg_store] All tables dropped.", flush=True)


# ---------------------------------------------------------------------------
# Schema application
# ---------------------------------------------------------------------------
def _apply_schema(conn) -> None:
    print("[pg_store] Applying schema …", flush=True)
    # psycopg2 doesn't support executescript, but can handle a full multi-statement
    # DDL string if we use autocommit + a single execute with the full SQL.
    # Split on CREATE TABLE boundaries so each statement is complete (avoids
    # splitting FK constraint clauses mid-statement when splitting on ';').
    import re as _re
    cur = conn.cursor()
    # Split into complete CREATE TABLE statements — each starts at 'CREATE TABLE'
    # and ends at the closing ');' of that statement.
    stmts = _re.split(r'(?=CREATE TABLE)', _SCHEMA_SQL, flags=_re.IGNORECASE)
    for stmt in stmts:
        stmt = stmt.strip()
        if not stmt or stmt.startswith("--"):
            continue
        # Remove any trailing comment lines before the final semicolon
        stmt = stmt.rstrip()
        if not stmt.endswith(";"):
            stmt += ";"
        cur.execute(stmt)
    conn.commit()
    cur.close()
    print("[pg_store] Schema applied.", flush=True)


# ---------------------------------------------------------------------------
# Load plan: (table_name, csv_path)
# FK-safe insertion order mirrors db_loader.py
# ---------------------------------------------------------------------------
def _load_plan(sql_dir: Path) -> list[tuple[str, Path]]:
    ksp = sql_dir / "ksp"
    master = ksp / "master"
    ext = sql_dir / "extension"
    return [
        # Masters
        ("State",           master / "State.csv"),
        ("District",        master / "District.csv"),
        ("UnitType",        master / "UnitType.csv"),
        ("Unit",            master / "Unit.csv"),
        ("Rank",            master / "Rank.csv"),
        ("Designation",     master / "Designation.csv"),
        ("Employee",        master / "Employee.csv"),
        ("Court",           master / "Court.csv"),
        ("CaseCategory",    master / "CaseCategory.csv"),
        ("GravityOffence",  master / "GravityOffence.csv"),
        ("CaseStatusMaster",master / "CaseStatusMaster.csv"),
        ("CrimeHead",       master / "CrimeHead.csv"),
        ("CrimeSubHead",    master / "CrimeSubHead.csv"),
        ("Act",             master / "Act.csv"),
        ("Section",         master / "Section.csv"),
        ("CrimeHeadActSection", master / "CrimeHeadActSection.csv"),
        ("CasteMaster",     master / "CasteMaster.csv"),
        ("ReligionMaster",  master / "ReligionMaster.csv"),
        ("OccupationMaster",master / "OccupationMaster.csv"),
        # KSP core
        ("CaseMaster",          ksp / "CaseMaster.csv"),
        ("ComplainantDetails",  ksp / "ComplainantDetails.csv"),
        ("Victim",              ksp / "Victim.csv"),
        ("Accused",             ksp / "Accused.csv"),
        ("ArrestSurrender",     ksp / "ArrestSurrender.csv"),
        ("ActSectionAssociation", ksp / "ActSectionAssociation.csv"),
        ("ChargesheetDetails",  ksp / "ChargesheetDetails.csv"),
        # Extension
        ("EXT_Account",     ext / "accounts.csv"),
        ("EXT_Phone",       ext / "phones.csv"),
        ("EXT_Device",      ext / "devices.csv"),
        ("EXT_UPI",         ext / "upis.csv"),
        ("EXT_IP",          ext / "ips.csv"),
        ("EXT_Wallet",      ext / "wallets.csv"),
        ("EXT_Transaction",          ext / "transactions.csv"),
        ("EXT_Uses",                 ext / "rels_uses.csv"),
        ("EXT_Mentions",             ext / "rels_mentions.csv"),
        ("EXT_AccusedIn",            ext / "rels_accused_in.csv"),
        ("EXT_ComplainantIn",        ext / "rels_complainant_in.csv"),
        ("EXT_CaseGeo",              ext / "case_geo.csv"),
        ("EXT_InvestigationReport",  ext / "investigation_reports.csv"),
        ("EXT_VictimDetail",         ext / "victim_details.csv"),
        ("EXT_AccusedDetail",        ext / "accused_details.csv"),
        ("EXT_SubEvent",             ext / "sub_events.csv"),
        ("EXT_LegalElement",         ext / "legal_elements.csv"),
        ("EXT_EvidenceType",         ext / "evidence_types.csv"),
        ("EXT_Precedent",            ext / "precedents.csv"),
        ("EXT_IPCSection",           ext / "ipc_sections.csv"),
    ]


# ---------------------------------------------------------------------------
# Public: run()
# ---------------------------------------------------------------------------
def run(wipe: bool = True) -> None:
    """Drop (if wipe), recreate schema, and load all CSVs into Postgres."""
    conn = _connect()
    try:
        if wipe:
            _wipe(conn)
            # Clear checkpoint so everything is reloaded fresh
            if _CHECKPOINT.exists():
                _CHECKPOINT.unlink()

        _apply_schema(conn)

        checkpoint = _load_checkpoint()
        plan = _load_plan(cfg.SQL_DIR)
        total = len(plan)

        cur = conn.cursor()
        for i, (table, csv_path) in enumerate(plan, 1):
            if checkpoint.get(table) == "done":
                print(f"[pg_store] [{i}/{total}] SKIP {table} (checkpoint)", flush=True)
                continue

            rows = _load_csv(csv_path)
            if not rows:
                print(f"[pg_store] [{i}/{total}] SKIP {table} — CSV not found or empty", flush=True)
                checkpoint[table] = "done"
                _save_checkpoint(checkpoint)
                continue

            n = _bulk_insert(cur, table, rows)
            conn.commit()
            print(f"[pg_store] [{i}/{total}] {table}: {n} rows", flush=True)

            checkpoint[table] = "done"
            _save_checkpoint(checkpoint)

        cur.close()

        # Row count summary
        cur = conn.cursor()
        print("\n[pg_store] Row counts:", flush=True)
        summary_tables = [
            "CaseMaster", "ComplainantDetails", "Victim", "Accused",
            "ArrestSurrender", "ActSectionAssociation", "ChargesheetDetails",
            "EXT_Account", "EXT_Transaction", "EXT_Uses", "EXT_Mentions",
            "EXT_AccusedIn", "EXT_ComplainantIn", "EXT_VictimDetail",
            "EXT_AccusedDetail", "EXT_SubEvent",
        ]
        for t in summary_tables:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            n = cur.fetchone()[0]
            print(f"  {t}: {n}", flush=True)
        cur.close()

    finally:
        conn.close()

    print("[pg_store] Done.", flush=True)


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import sys
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    parser = argparse.ArgumentParser(description="Load KSP CSVs into Postgres")
    parser.add_argument("--no-wipe", action="store_true", help="Skip drop; resume from checkpoint")
    args = parser.parse_args()
    try:
        run(wipe=not args.no_wipe)
    except Exception as e:
        print(f"[pg_store] FAILED: {e}", flush=True)
        sys.exit(1)
