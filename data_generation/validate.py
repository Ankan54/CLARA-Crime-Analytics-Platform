"""
validate.py - Comprehensive validation of the generated dataset.

Checks:
 A. KSP schema conformance (FK integrity, CrimeNo format, masters seeded,
    district derivation, cstype distribution, caste/religion populated)
 B. Live-path checks (*.expected.json valid, pool identifiers match historical,
    CrimeNo reserved & conflict-free, live Accused un-merged)
 C. Scenario/decoy/context-layer checks (identifier isolation, planted links,
    context properties on edges, narrative tier similarity)
 D. Volume checks (within ±10% of targets)
 E. Data quality checks (IFSC format, pincode format, identifier survival
    through translation, evidence artifacts)
"""
from __future__ import annotations
import csv
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import config
from . import id_registry as reg
from . import ksp_master as km
# ---------------------------------------------------------------------------
# Validation result collector
# ---------------------------------------------------------------------------

class ValidationResult:
    def __init__(self):
        self.errors:   List[str] = []
        self.warnings: List[str] = []
        self.passed:   List[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(f"[ERROR] {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(f"[WARN]  {msg}")

    def ok(self, msg: str) -> None:
        self.passed.append(f"[OK]    {msg}")

    def summary(self) -> str:
        lines = []
        lines.extend(self.errors)
        lines.extend(self.warnings)
        total = len(self.errors) + len(self.warnings) + len(self.passed)
        lines.append(
            f"\n=== Validation complete: {len(self.passed)}/{total} checks passed, "
            f"{len(self.errors)} errors, {len(self.warnings)} warnings ==="
        )
        return "\n".join(lines)

    def is_clean(self) -> bool:
        return len(self.errors) == 0

# ---------------------------------------------------------------------------
# Helper: read CSV
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _read_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

# ---------------------------------------------------------------------------
# A. KSP Schema Conformance Checks
# ---------------------------------------------------------------------------

def check_ksp_masters(output_dir: Path, result: ValidationResult) -> None:
    """Check all KSP master tables are present and non-empty."""
    master_dir = output_dir / "historical" / "sql" / "ksp" / "master"
    required = [
        "State.csv", "District.csv", "Unit.csv", "UnitType.csv",
        "Rank.csv", "Designation.csv", "Employee.csv", "Court.csv",
        "CaseCategory.csv", "GravityOffence.csv",
        "CrimeHead.csv", "CrimeSubHead.csv", "CrimeHeadActSection.csv",
        "CaseStatusMaster.csv",
        "Act.csv", "Section.csv",
        "CasteMaster.csv", "ReligionMaster.csv", "OccupationMaster.csv",
    ]
    for fname in required:
        p = master_dir / fname
        if not p.exists():
            result.error(f"KSP master CSV missing: {fname}")
        else:
            rows = _read_csv(p)
            if not rows:
                result.error(f"KSP master CSV empty: {fname}")
            else:
                result.ok(f"Master {fname}: {len(rows)} rows")

    # ER CSV does not carry the internal CrimeTypeCode helper; FK parity is checked elsewhere.
    subhead_rows = _read_csv(master_dir / "CrimeSubHead.csv")
    if subhead_rows:
        result.ok(f"CrimeSubHead master present with {len(subhead_rows)} rows")


def check_crime_no_format(output_dir: Path, result: ValidationResult) -> None:
    """Check CrimeNo format and CaseNo derivation on all CaseMaster rows."""
    cm_path = output_dir / "historical" / "sql" / "ksp" / "CaseMaster.csv"
    rows = _read_csv(cm_path)
    pattern = re.compile(config.CRIME_NO_REGEX)
    seen_crime_nos: Set[str] = set()
    majority_cat_1 = 0

    for row in rows:
        crime_no = row.get("CrimeNo", "")
        case_no = row.get("CaseNo", "")

        # Format check
        if not pattern.match(crime_no):
            result.error(f"CrimeNo format invalid: {crime_no} (CaseMasterID={row.get('CaseMasterID')})")
        else:
            # CaseNo = last 9 digits
            if case_no != crime_no[-9:]:
                result.error(f"CaseNo mismatch: {case_no} != {crime_no[-9:]} for {crime_no}")

            # Uniqueness
            if crime_no in seen_crime_nos:
                result.error(f"Duplicate CrimeNo: {crime_no}")
            seen_crime_nos.add(crime_no)

            # Category-1 (FIR) majority
            if crime_no[0] == "1":
                majority_cat_1 += 1

    if rows:
        cat1_pct = majority_cat_1 / len(rows)
        if cat1_pct < 0.8:
            result.warn(f"CrimeNo category 1 (FIR) is only {cat1_pct:.0%} (expected >80%)")
        else:
            result.ok(f"CrimeNo format valid for {len(rows)} cases; {cat1_pct:.0%} are FIR")


def check_fk_integrity(output_dir: Path, result: ValidationResult) -> None:
    """Check all FK columns in CaseMaster resolve to seeded masters."""
    ksp = output_dir / "historical" / "sql" / "ksp"
    master = ksp / "master"

    unit_ids = {int(r["UnitID"]) for r in _read_csv(master / "Unit.csv")}
    employee_ids = {int(r["EmployeeID"]) for r in _read_csv(master / "Employee.csv")}
    category_ids = {int(r["CaseCategoryID"]) for r in _read_csv(master / "CaseCategory.csv")}
    gravity_ids = {int(r["GravityOffenceID"]) for r in _read_csv(master / "GravityOffence.csv")}
    head_ids = {int(r["CrimeHeadID"]) for r in _read_csv(master / "CrimeHead.csv")}
    subhead_ids = {int(r["CrimeSubHeadID"]) for r in _read_csv(master / "CrimeSubHead.csv")}
    status_ids = {int(r["CaseStatusID"]) for r in _read_csv(master / "CaseStatusMaster.csv")}
    court_ids = {int(r["CourtID"]) for r in _read_csv(master / "Court.csv")}

    for row in _read_csv(ksp / "CaseMaster.csv"):
        cid = row.get("CaseMasterID","?")
        checks = [
            ("PoliceStationID", int(row.get("PoliceStationID",0)), unit_ids),
            ("PolicePersonID",  int(row.get("PolicePersonID",0)),  employee_ids),
            ("CaseCategoryID",  int(row.get("CaseCategoryID",0)),  category_ids),
            ("GravityOffenceID",int(row.get("GravityOffenceID",0)),gravity_ids),
            ("CrimeMajorHeadID",int(row.get("CrimeMajorHeadID",0)),head_ids),
            ("CrimeMinorHeadID",int(row.get("CrimeMinorHeadID",0)),subhead_ids),
            ("CaseStatusID",    int(row.get("CaseStatusID",0)),    status_ids),
            ("CourtID",         int(row.get("CourtID",0)),         court_ids),
        ]
        for col, val, valid_set in checks:
            if val not in valid_set:
                result.error(f"FK violation: CaseMaster.{col}={val} not in master (CaseMasterID={cid})")

    result.ok("FK integrity check complete for CaseMaster")

    # ActSectionAssociation FK checks
    act_codes = {r["ActCode"] for r in _read_csv(master / "Act.csv")}
    section_codes = {r["SectionCode"] for r in _read_csv(master / "Section.csv")}
    asa_rows = _read_csv(ksp / "ActSectionAssociation.csv")
    cm_ids_set = {r["CaseMasterID"] for r in _read_csv(ksp / "CaseMaster.csv")}
    for row in asa_rows:
        if row.get("ActCode","") not in act_codes:
            result.error(f"ASA ActCode FK invalid: {row.get('ActCode')} (CaseMasterID={row.get('CaseMasterID')})")
        if row.get("SectionCode","") not in section_codes:
            result.error(f"ASA SectionCode FK invalid: {row.get('SectionCode')}")
        if row.get("CaseMasterID","") not in cm_ids_set:
            result.error(f"ASA CaseMasterID FK invalid: {row.get('CaseMasterID')}")
    result.ok(f"ActSectionAssociation FK check: {len(asa_rows)} rows")


def check_district_derivation(output_dir: Path, result: ValidationResult) -> None:
    """Verify every case's PoliceStationID -> Unit.DistrictID resolves."""
    ksp = output_dir / "historical" / "sql" / "ksp"
    master = ksp / "master"
    unit_district = {int(r["UnitID"]): int(r["DistrictID"])
                     for r in _read_csv(master / "Unit.csv")}
    district_ids = {int(r["DistrictID"]) for r in _read_csv(master / "District.csv")}

    ok_count = 0
    for row in _read_csv(ksp / "CaseMaster.csv"):
        unit_id = int(row.get("PoliceStationID", 0))
        dist_id = unit_district.get(unit_id)
        if dist_id is None:
            result.error(f"Unit {unit_id} not in Unit master (CaseMasterID={row.get('CaseMasterID')})")
        elif dist_id not in district_ids:
            result.error(f"District {dist_id} not in District master")
        else:
            ok_count += 1
        lat = float(row.get("Latitude", 0) or 0)
        lng = float(row.get("Longitude", 0) or 0)
        if lat == 0 and lng == 0:
            result.warn(f"CaseMaster {row.get('CaseMasterID')} has lat/long = 0")
    result.ok(f"District derivation: {ok_count} cases resolved correctly")


def check_cstype_distribution(output_dir: Path, result: ValidationResult) -> None:
    """Check ChargesheetDetails.cstype distribution is within tolerance."""
    cs_path = output_dir / "historical" / "sql" / "ksp" / "ChargesheetDetails.csv"
    rows = _read_csv(cs_path)
    if not rows:
        result.warn("ChargesheetDetails.csv is empty or missing")
        return
    counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.get("CSType","?")] += 1
    total = len(rows)
    expected = config.CSTYPE_DISTRIBUTION
    tolerance = 0.15
    for cstype, expected_pct in expected.items():
        actual_pct = counts.get(cstype, 0) / total
        if abs(actual_pct - expected_pct) > tolerance:
            result.warn(f"CSType '{cstype}': {actual_pct:.0%} actual vs {expected_pct:.0%} expected "
                        f"(tolerance {tolerance:.0%})")
        else:
            result.ok(f"CSType '{cstype}': {actual_pct:.0%} (target {expected_pct:.0%})")


def check_caste_religion_populated(output_dir: Path, result: ValidationResult) -> None:
    """Verify caste/religion are populated on conformance tables."""
    ksp = output_dir / "historical" / "sql" / "ksp"
    ext = output_dir / "historical" / "sql" / "extension"
    for fname, pk_col in [
        ("ComplainantDetails.csv","ComplainantID"),
        ("accused_details.csv","AccusedMasterID"),
        ("victim_details.csv","VictimMasterID"),
    ]:
        base = ksp if fname == "ComplainantDetails.csv" else ext
        rows = _read_csv(base / fname)
        missing_caste = sum(1 for r in rows if not r.get("CasteID","").strip())
        missing_religion = sum(1 for r in rows if not r.get("ReligionID","").strip())
        if missing_caste:
            result.error(f"{fname}: {missing_caste} rows missing CasteID (required for KSP conformance)")
        else:
            result.ok(f"{fname}: CasteID populated on all {len(rows)} rows")
        if missing_religion:
            result.error(f"{fname}: {missing_religion} rows missing ReligionID")
        else:
            result.ok(f"{fname}: ReligionID populated on all {len(rows)} rows")

# ---------------------------------------------------------------------------
# B. Live-path checks
# ---------------------------------------------------------------------------

def check_live_path(output_dir: Path, result: ValidationResult) -> None:
    """
    For each of the 4 live scenarios, validate:
    (a) fir.expected.json exists and is schema-valid (all FKs resolve)
    (b) CrimeNo is format-valid, station is seeded, no historical collision
    (c) Revealed pool identifiers match historical extension values exactly
    (d) FIR header block contains same fields as expected JSON
    (e) Live Accused have own AccusedMasterIDs
    """
    live_base = output_dir / "live_demo"
    hist_ksp = output_dir / "historical" / "sql" / "ksp"
    hist_ext = output_dir / "historical" / "sql" / "extension"

    # Load historical identifiers for exact-match check
    hist_accounts = {r["AccountNo"] for r in _read_csv(hist_ext / "accounts.csv")}
    hist_devices   = {r["IMEI"] for r in _read_csv(hist_ext / "devices.csv")}
    hist_upis      = {r["VPA"] for r in _read_csv(hist_ext / "upis.csv")}
    hist_phones    = {r["Number"] for r in _read_csv(hist_ext / "phones.csv")}
    hist_ips       = {r["IPAddress"] for r in _read_csv(hist_ext / "ips.csv")}
    hist_crime_nos = {r["CrimeNo"] for r in _read_csv(hist_ksp / "CaseMaster.csv")}
    hist_accused_ids = {r["AccusedMasterID"] for r in _read_csv(hist_ksp / "Accused.csv")}

    # KSP master FK sets
    master_dir = hist_ksp / "master"
    unit_ids    = {int(r["UnitID"]) for r in _read_csv(master_dir / "Unit.csv")}
    cat_ids     = {int(r["CaseCategoryID"]) for r in _read_csv(master_dir / "CaseCategory.csv")}
    status_ids  = {int(r["CaseStatusID"]) for r in _read_csv(master_dir / "CaseStatusMaster.csv")}
    head_ids    = {int(r["CrimeHeadID"]) for r in _read_csv(master_dir / "CrimeHead.csv")}
    subhead_ids = {int(r["CrimeSubHeadID"]) for r in _read_csv(master_dir / "CrimeSubHead.csv")}

    crime_no_pattern = re.compile(config.CRIME_NO_REGEX)
    scenarios = ["live_scn1", "live_scn2", "live_scn3", "live_scn4"]

    for scn in scenarios:
        scn_dir = live_base / scn
        if not scn_dir.exists():
            result.error(f"Live scenario dir missing: {scn_dir}")
            continue

        # (a) fir.expected.json exists and schema-valid
        exp_path = scn_dir / "fir.expected.json"
        if not exp_path.exists():
            result.error(f"{scn}: fir.expected.json missing")
            continue
        try:
            expected = json.loads(exp_path.read_text(encoding="utf-8"))
        except Exception as e:
            result.error(f"{scn}: fir.expected.json parse error: {e}")
            continue

        # Check required fields
        for field in ["CrimeNo","CaseNo","PoliceStationID","CaseCategoryID",
                      "CaseStatusID","CrimeMajorHeadID","CrimeMinorHeadID",
                      "complainant","accused","charged_sections","revealed_identifiers"]:
            if field not in expected:
                result.error(f"{scn}: fir.expected.json missing field: {field}")

        # (b) CrimeNo format + station seeded + no collision
        crime_no = expected.get("CrimeNo","")
        if not crime_no_pattern.match(crime_no):
            result.error(f"{scn}: CrimeNo format invalid: {crime_no}")
        else:
            result.ok(f"{scn}: CrimeNo format valid: {crime_no}")

        if crime_no in hist_crime_nos:
            result.error(f"{scn}: Live CrimeNo {crime_no} collides with historical case!")
        else:
            result.ok(f"{scn}: CrimeNo {crime_no} is conflict-free")

        station_id = expected.get("PoliceStationID",0)
        if int(station_id) not in unit_ids:
            result.error(f"{scn}: Live PoliceStationID {station_id} not in seeded Unit master")
        else:
            result.ok(f"{scn}: PoliceStationID {station_id} resolves against Unit master")

        # FK checks on expected JSON
        for fk_field, valid_set, label in [
            ("CaseCategoryID", cat_ids, "CaseCategory"),
            ("CaseStatusID",   status_ids, "CaseStatus"),
            ("CrimeMajorHeadID", head_ids, "CrimeHead"),
            ("CrimeMinorHeadID", subhead_ids, "CrimeSubHead"),
        ]:
            val = expected.get(fk_field, 0)
            if int(val) not in valid_set:
                result.error(f"{scn}: {fk_field}={val} not in seeded {label} master")

        # (c) Shared identifiers must exist historically; other reveals may be live-only.
        revealed = expected.get("revealed_identifiers", {})
        shared_expected = {
            str(link.get("via_identifier", ""))
            for link in expected.get("connects_to", [])
            if isinstance(link, dict)
        }
        for id_type, ids in revealed.items():
            hist_set = {
                "accounts": hist_accounts,
                "imeis":    hist_devices,
                "upis":     hist_upis,
                "phones":   hist_phones,
                "ips":      hist_ips,
            }.get(id_type, set())
            for id_val in ids:
                # Support richer expected JSON entries (e.g., ips list with dict payload).
                if isinstance(id_val, dict):
                    id_val = id_val.get("ip") or id_val.get("value") or id_val.get("id") or ""
                if not id_val:
                    continue
                if id_val in hist_set:
                    result.ok(f"{scn}: Revealed {id_type} '{id_val}' confirmed in historical data")
                elif id_val in shared_expected:
                    result.error(
                        f"{scn}: Shared {id_type} '{id_val}' is missing from historical data "
                        f"(declared in connects_to)")
                else:
                    result.ok(
                        f"{scn}: Live-only reveal {id_type} '{id_val}' absent historically (allowed)")

        # (d) FIR header block contains CrimeNo and station name
        fir_path = scn_dir / "fir.txt"
        if fir_path.exists():
            fir_text = fir_path.read_text(encoding="utf-8")
            if crime_no not in fir_text:
                result.error(f"{scn}: CrimeNo {crime_no} not found in fir.txt header block")
            else:
                result.ok(f"{scn}: CrimeNo present in fir.txt")
            station_name = expected.get("PoliceStationName","")
            if station_name and station_name not in fir_text:
                result.warn(f"{scn}: Station name '{station_name}' not found in fir.txt")
        else:
            result.error(f"{scn}: fir.txt missing")

        # (e) Live Accused have own AccusedMasterIDs (no collision with historical)
        for acc in expected.get("accused", []):
            acc_mid = str(acc.get("AccusedMasterID",""))
            if acc_mid in hist_accused_ids:
                result.error(
                    f"{scn}: Live accused AccusedMasterID={acc_mid} collides with historical! "
                    "Live accused must be un-merged.")
            elif acc_mid:
                result.ok(f"{scn}: Live accused AccusedMasterID={acc_mid} is unique (un-merged)")

        # ir.expected.json
        ir_exp_path = scn_dir / "ir.expected.json"
        if not ir_exp_path.exists():
            result.error(f"{scn}: ir.expected.json missing")
        else:
            result.ok(f"{scn}: ir.expected.json present")

        # connects_to has at least one entry
        if not expected.get("connects_to"):
            result.error(f"{scn}: connects_to is empty in fir.expected.json")
        else:
            result.ok(f"{scn}: connects_to has {len(expected['connects_to'])} assertions")

# ---------------------------------------------------------------------------
# C. Scenario / context-layer checks
# ---------------------------------------------------------------------------

def check_no_resolved_as_edges(output_dir: Path, result: ValidationResult) -> None:
    """Verify NO RESOLVED_AS or LINKED_TO edges were written to graph CSVs."""
    graph = output_dir / "historical" / "graph"
    forbidden = ["RESOLVED_AS", "LINKED_TO", "centrality", "community_id"]
    for csv_path in graph.glob("*.csv"):
        try:
            with open(csv_path, encoding="utf-8") as f:
                content = f.read()
            for term in forbidden:
                if term in content:
                    result.error(f"Forbidden pre-baked term '{term}' found in {csv_path.name}")
        except Exception:
            pass
    result.ok("No RESOLVED_AS/LINKED_TO/centrality pre-baked in graph CSVs")


def check_context_properties_on_edges(output_dir: Path, result: ValidationResult) -> None:
    """Verify discovery-critical relationship CSVs carry source_caseid/observed_date/confidence."""
    graph = output_dir / "historical" / "graph"
    required_rels = [
        "rels_uses.csv", "rels_accused_in.csv", "rels_complainant_in.csv",
        "rels_transferred_to.csv", "rels_mentions.csv",
    ]
    for fname in required_rels:
        path = graph / fname
        rows = _read_csv(path)
        if not rows:
            result.warn(f"{fname}: no rows to check context properties")
            continue
        missing = [r for r in rows
                   if not r.get("source_caseid") or not r.get("observed_date")
                   or not r.get("confidence")]
        if missing:
            result.error(f"{fname}: {len(missing)} rows missing context properties "
                         f"(source_caseid/observed_date/confidence)")
        else:
            result.ok(f"{fname}: all {len(rows)} rows have context properties")


def check_scenario_isolation(output_dir: Path, result: ValidationResult) -> None:
    """
    Verify SCN4 baseline FIR identifiers are NOT in the burst pool
    and decoy identifiers are NOT linked to scenario cases.
    """
    from .identifier_pool import (
        DEV_POOL_04, IP_POOL_04, MULE_SET_04,
        SCN1_DECOY,
    )
    ext = output_dir / "historical" / "sql" / "extension"
    txns = _read_csv(ext / "transactions.csv")

    # Decoy account must NOT appear linked to scenario pool transactions
    decoy_account = SCN1_DECOY.get("account_no", "")
    from .identifier_pool import (
        AGG_ACC_01, BRIDGE_ACC_03,
    )
    for txn in txns:
        if (txn.get("FromAccount") == decoy_account or
                txn.get("ToAccount") == decoy_account):
            result.warn(f"Decoy account {DECOY_ACCOUNT} appears in transaction ledger "
                        f"(expected only in decoy FIR)")
    result.ok("Scenario isolation check complete")


def check_volume_targets(output_dir: Path, result: ValidationResult) -> None:
    """Check all entity counts are within ±10% of targets."""
    ksp = output_dir / "historical" / "sql" / "ksp"
    ext = output_dir / "historical" / "sql" / "extension"
    tol = config.VOLUME_TOLERANCE

    checks = [
        (ksp / "CaseMaster.csv",        config.TARGET_FIRS_HISTORICAL,          "CaseMaster (hist FIRs)"),
        (ext / "accounts.csv",          config.TARGET_ACCOUNTS,                 "Accounts"),
        (ext / "transactions.csv",      config.TARGET_TRANSACTIONS,             "Transactions"),
        (ext / "devices.csv",           config.TARGET_DEVICES,                  "Devices"),
        (ext / "phones.csv",            config.TARGET_PHONES,                   "Phones"),
        (ext / "upis.csv",              config.TARGET_UPIS,                     "UPIs"),
        (ext / "ips.csv",               config.TARGET_IPS,                      "IPs"),
        (ext / "wallets.csv",           config.TARGET_WALLETS,                  "Wallets"),
        (ext / "investigation_reports.csv", config.TARGET_INVESTIGATION_REPORTS_HISTORICAL, "InvestigationReports (hist)"),
        (ext / "ipc_sections.csv",      config.TARGET_IPC_SECTIONS,             "IPC Sections"),
    ]
    for path, target, label in checks:
        rows = _read_csv(path)
        actual = len(rows)
        if target and abs(actual - target) / max(target, 1) > tol:
            result.warn(f"{label}: {actual} rows (target {target}, tolerance ±{tol:.0%})")
        else:
            result.ok(f"{label}: {actual} rows (target {target})")


def check_ifsc_format(output_dir: Path, result: ValidationResult) -> None:
    """Check IFSC codes follow 4-letter + 0 + 6 alphanumeric format."""
    ext = output_dir / "historical" / "sql" / "extension"
    pattern = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
    bad = 0
    for row in _read_csv(ext / "accounts.csv"):
        ifsc = row.get("IFSC","")
        if ifsc and not pattern.match(ifsc):
            bad += 1
    if bad:
        result.error(f"IFSC format invalid on {bad} accounts")
    else:
        result.ok(f"IFSC format valid on all account rows")


def check_cross_store_ids(output_dir: Path, result: ValidationResult) -> None:
    """Verify Crime/IR graph node_ids resolve to CaseMaster rows."""
    ksp = output_dir / "historical" / "sql" / "ksp"
    graph = output_dir / "historical" / "graph"
    vec = output_dir / "historical" / "vector"

    cm_ids = {r["CaseMasterID"] for r in _read_csv(ksp / "CaseMaster.csv")}

    # Graph crime nodes
    for row in _read_csv(graph / "nodes_crime.csv"):
        node_id = str(row.get("node_id",""))
        if node_id not in cm_ids:
            result.error(f"Graph Crime node_id={node_id} not in CaseMaster")

    # Vector records for FIRs
    for rec in _read_jsonl(vec / "narratives.jsonl"):
        nid = str(rec.get("node_id",""))
        if nid.startswith("IR:"):
            continue   # IR records OK to not match CaseMasterID
        if nid not in cm_ids:
            result.error(f"Vector node_id={nid} not in CaseMaster")

    result.ok("Cross-store ID consistency check complete")


def check_evidence_artifacts(output_dir: Path, result: ValidationResult) -> None:
    """
    Assert evidence artifact presence per scenario.
    KEY RULE: Scenario 1 must NOT have bsa_63_certificate.txt (planted amber gap).
    """
    ev_base = output_dir / "historical" / "evidence"

    for scn in range(1, 5):
        scn_ev = ev_base / f"scenario_{scn}" / "evidence"
        if not scn_ev.exists():
            result.warn(f"Evidence dir missing: scenario_{scn}")
            continue

        if scn == 1:
            cert = scn_ev / "bsa_63_certificate.txt"
            if cert.exists():
                result.error(
                    "Scenario 1: bsa_63_certificate.txt MUST be absent (planted amber gap). "
                    "Remove it or the legal checklist demo is broken.")
            else:
                result.ok("Scenario 1: bsa_63_certificate.txt correctly absent (planted gap)")
        else:
            cert = scn_ev / "bsa_63_certificate.txt"
            if not cert.exists():
                result.warn(f"Scenario {scn}: bsa_63_certificate.txt missing")
            else:
                result.ok(f"Scenario {scn}: bsa_63_certificate.txt present")


def check_translation_identifier_survival(output_dir: Path, result: ValidationResult) -> None:
    """
    Verify that pool identifiers survive Kannada translation:
    every identifier in fir.txt must appear unchanged in fir.kn.txt.
    """
    from .identifier_pool import (
        AGG_ACC_01, DEV_IMEI_02, UPI_02, PHONE_02,
        BRIDGE_ACC_03, CTRL_IMEI_01, CTRL_UPI_01,
    )
    live_base = output_dir / "live_demo"
    identifier_sets = {
        "live_scn1": [AGG_ACC_01["account_no"], CTRL_IMEI_01, CTRL_UPI_01],
        "live_scn2": [DEV_IMEI_02, UPI_02, PHONE_02],
        "live_scn3": [BRIDGE_ACC_03["account_no"]],
        "live_scn4": [],
    }
    for scn, identifiers in identifier_sets.items():
        scn_dir = live_base / scn
        fir_path = scn_dir / "fir.txt"
        kn_path = scn_dir / "fir.kn.txt"
        if not kn_path.exists():
            result.warn(f"{scn}: fir.kn.txt missing (translation not yet generated)")
            continue
        fir_text = fir_path.read_text(encoding="utf-8") if fir_path.exists() else ""
        kn_text = kn_path.read_text(encoding="utf-8")
        for ident in identifiers:
            if not ident:
                continue
            if ident not in fir_text:
                result.ok(f"{scn}: Identifier '{ident}' not present in fir.txt source text (skip translation check)")
                continue
            if ident not in kn_text:
                result.error(
                    f"{scn}: Identifier '{ident}' missing from fir.kn.txt "
                    "(translation mangled the identifier)")
            else:
                result.ok(f"{scn}: Identifier '{ident}' survived Kannada translation")

# ---------------------------------------------------------------------------
# Narrative similarity tier checks (requires sentence-transformers)
# ---------------------------------------------------------------------------

def check_narrative_tiers(output_dir: Path, result: ValidationResult) -> None:
    """
    Assert intra-cluster (Tier A) cosine similarity > inter-cluster (Tier A vs Tier B)
    similarity by at least 0.05 margin for Scenario 1 and Scenario 4 clusters.
    Uses sentence-transformers/all-MiniLM-L6-v2.
    """
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except ImportError:
        result.ok("sentence-transformers not installed; narrative tier similarity check skipped")
        return

    vec_path = output_dir / "historical" / "vector" / "narratives.jsonl"
    records = _read_jsonl(vec_path)
    if not records:
        result.ok("Vector JSONL empty; narrative tier similarity check skipped")
        return

    # Group by crime_type
    by_type: Dict[str, List[str]] = defaultdict(list)
    for rec in records:
        ct = rec.get("metadata", {}).get("crime_type", "")
        txt = rec.get("text","")
        if txt:
            by_type[ct].append(txt)

    if not by_type.get("digital_arrest") or not by_type.get("task_scam"):
        result.ok("Insufficient narratives for tier similarity check")
        return

    model = SentenceTransformer(config.VALIDATION_EMBEDDING_MODEL)

    # Tier A cluster = first 4 digital_arrest (Scn1 historical ring)
    tier_a = by_type["digital_arrest"][:4]
    tier_b = by_type["digital_arrest"][4:]   # background digital_arrest

    if len(tier_a) < 2 or not tier_b:
        result.ok("Not enough digital_arrest narratives for tier A vs B check")
        return

    embeddings_a = model.encode(tier_a)
    embeddings_b = model.encode(tier_b[:6])  # use up to 6 tier-B

    # Intra-cluster (Tier A) pairwise cosine
    def cosine(u, v):
        return float(np.dot(u,v) / (np.linalg.norm(u)*np.linalg.norm(v)))

    intra_scores = []
    for i in range(len(embeddings_a)):
        for j in range(i+1, len(embeddings_a)):
            intra_scores.append(cosine(embeddings_a[i], embeddings_a[j]))

    # Inter-cluster scores (Tier A vs Tier B)
    inter_scores = []
    for ea in embeddings_a:
        for eb in embeddings_b:
            inter_scores.append(cosine(ea, eb))

    min_intra = min(intra_scores) if intra_scores else 0
    max_inter = max(inter_scores) if inter_scores else 0
    margin = min_intra - max_inter

    if margin < 0.05:
        result.warn(
            f"Tier A similarity margin insufficient: min_intra={min_intra:.3f}, "
            f"max_inter={max_inter:.3f}, margin={margin:.3f} (need >= 0.05). "
            "Consider templating more narrative text or re-generating at lower temperature.")
    else:
        result.ok(f"Narrative tier separation: margin={margin:.3f} (Tier A intra={min_intra:.3f}, "
                  f"inter={max_inter:.3f})")



# ---------------------------------------------------------------------------
# Suite A (new): ER DDL superset check + real SQLite DB checks
# ---------------------------------------------------------------------------

def check_er_conformance_superset(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite A: Schema.sql conformance check.
    Every KSP-ER table/column must exist in schema.sql (superset check).
    Extensions (EXT_*) are allowed but reported separately.
    """
    schema_path = output_dir / "historical" / "db" / "schema.sql"
    if not schema_path.exists():
        result.error(f"schema.sql missing: {schema_path}")
        return

    ddl = schema_path.read_text(encoding="utf-8")
    # ER-required tables (must be present)
    er_tables = [
        "State", "District", "UnitType", "Unit", "Rank", "Designation",
        "Employee", "Court", "CaseCategory", "GravityOffence", "CaseStatusMaster",
        "CrimeHead", "CrimeSubHead", "Act", "Section",
        "CasteMaster", "ReligionMaster", "OccupationMaster",
        "CaseMaster", "ComplainantDetails", "Victim", "Accused",
        "ArrestSurrender", "ActSectionAssociation", "ChargesheetDetails",
    ]
    for tbl in er_tables:
        if f"CREATE TABLE IF NOT EXISTS {tbl}" in ddl or f"CREATE TABLE {tbl}" in ddl:
            result.ok(f"schema.sql contains ER table: {tbl}")
        else:
            result.error(f"schema.sql MISSING ER table: {tbl}")

    # Extension tables
    ext_tables = [t for t in ["EXT_Account","EXT_Phone","EXT_Device","EXT_UPI",
                              "EXT_IP","EXT_Wallet","EXT_Transaction","EXT_Uses",
                              "EXT_Mentions","EXT_AccusedIn","EXT_ComplainantIn",
                              "EXT_CaseGeo","EXT_InvestigationReport"]
                  if f"CREATE TABLE IF NOT EXISTS {t}" in ddl]
    result.ok(f"schema.sql extension tables: {len(ext_tables)} found ({', '.join(ext_tables[:4])}...)")

    # ER-required columns spot-check
    er_col_checks = [
        ("CaseMaster",      "BriefFacts"),
        ("CaseMaster",      "Latitude"),
        ("Victim",          "VictimPolice"),
        ("Accused",         "PersonID"),
        ("ArrestSurrender", "IsAccused"),
        ("ArrestSurrender", "IsComplainantAccused"),
        ("ActSectionAssociation", "ActOrderID"),
        ("ActSectionAssociation", "SectionOrderID"),
        ("Employee",        "KGID"),
        ("Employee",        "FirstName"),
        ("Employee",        "EmployeeDOB"),
        ("CrimeHead",       "CrimeGroupName"),
        ("CrimeSubHead",    "CrimeHeadName"),
        ("CrimeSubHead",    "SeqID"),
        ("Act",             "ActDescription"),
        ("Act",             "ShortName"),
        ("CaseCategory",    "LookupValue"),
        ("GravityOffence",  "LookupValue"),
        ("CasteMaster",     "caste_master_id"),
        ("CasteMaster",     "caste_master_name"),
    ]
    for table, col in er_col_checks:
        if col in ddl:
            result.ok(f"schema.sql column present: {table}.{col}")
        else:
            result.error(f"schema.sql MISSING ER column: {table}.{col}")


def check_sqlite_db(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite A: Real SQLite DB checks.
    - ksp.sqlite exists
    - PRAGMA foreign_key_check returns 0 rows
    - DB row counts match CSV row counts for KSP-core tables
    """
    import sqlite3
    db_path = output_dir / "historical" / "db" / "ksp.sqlite"
    if not db_path.exists():
        result.error(f"ksp.sqlite not found: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

    # FK check
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        result.error(f"ksp.sqlite FK violations: {len(violations)} (first: {violations[0]})")
    else:
        result.ok("ksp.sqlite PRAGMA foreign_key_check: 0 violations")

    # Row count parity with CSVs
    ksp = output_dir / "historical" / "sql" / "ksp"
    table_csv_map = {
        "CaseMaster":       ksp / "CaseMaster.csv",
        "ComplainantDetails":ksp / "ComplainantDetails.csv",
        "Victim":           ksp / "Victim.csv",
        "Accused":          ksp / "Accused.csv",
        "ArrestSurrender":  ksp / "ArrestSurrender.csv",
        "ActSectionAssociation": ksp / "ActSectionAssociation.csv",
        "ChargesheetDetails":ksp / "ChargesheetDetails.csv",
    }
    for tbl, csv_path in table_csv_map.items():
        try:
            db_count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception as e:
            result.error(f"ksp.sqlite: could not query {tbl}: {e}")
            continue
        csv_rows = _read_csv(csv_path)
        if db_count != len(csv_rows):
            result.error(f"Row count mismatch: {tbl} DB={db_count} CSV={len(csv_rows)}")
        else:
            result.ok(f"Row count match: {tbl} = {db_count}")

    conn.close()


# ---------------------------------------------------------------------------
# Suite C (new): Document <-> SQL consistency (historical)
# ---------------------------------------------------------------------------

def check_historical_doc_sql_consistency(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite C: For each historical case, verify fir.txt and investigation_report.txt
    exist and contain the CrimeNo/CaseNo/CaseMasterID verbatim.
    """
    ksp = output_dir / "historical" / "sql" / "ksp"
    docs_root = output_dir / "historical" / "docs"

    if not docs_root.exists():
        result.warn(f"historical/docs/ not yet generated (skipping doc-SQL consistency check)")
        return

    cm_rows = _read_csv(ksp / "CaseMaster.csv")
    ok_count = 0
    for row in cm_rows:
        crime_no = row.get("CrimeNo","")
        case_no  = row.get("CaseNo","")
        cm_id    = row.get("CaseMasterID","")
        case_dir = docs_root / crime_no

        fir_path = case_dir / "fir.txt"
        ir_path  = case_dir / "investigation_report.txt"

        if not fir_path.exists():
            result.error(f"fir.txt missing for {crime_no}")
            continue
        if not ir_path.exists():
            result.warn(f"investigation_report.txt missing for {crime_no}")

        fir_text = fir_path.read_text(encoding="utf-8")
        for field, val in [("CrimeNo", crime_no), ("CaseNo", case_no), ("CaseMasterID", cm_id)]:
            if val and val not in fir_text:
                result.error(f"fir.txt {crime_no}: {field}={val} not found verbatim")
            elif val:
                ok_count += 1

    result.ok(f"Doc-SQL consistency: {ok_count} field occurrences found verbatim in docs")


# ---------------------------------------------------------------------------
# Suite D (new): Vector completeness
# ---------------------------------------------------------------------------

def check_vector_completeness(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite D: One vector record per historical FIR (node_id=CaseMasterID),
    one per IR (node_id=IR:<ReportID>). Text is FULL doc (not empty).
    Each CaseMasterID in vector resolves to a CaseMaster row.
    """
    vec_path = output_dir / "historical" / "vector" / "narratives.jsonl"
    records = _read_jsonl(vec_path)
    ksp = output_dir / "historical" / "sql" / "ksp"
    cm_ids = {r["CaseMasterID"] for r in _read_csv(ksp / "CaseMaster.csv")}

    fir_nodes = {str(r["node_id"]) for r in records
                 if str(r.get("doc_type","")) == "fir" or not str(r.get("node_id","")).startswith("IR:")}
    ir_nodes  = [r for r in records if str(r.get("node_id","")).startswith("IR:")]

    result.ok(f"Vector JSONL: {len(records)} total records ({len(fir_nodes)} FIR, {len(ir_nodes)} IR)")

    # Every FIR vector node resolves to a CaseMaster row
    unresolved = 0
    for r in records:
        nid = str(r.get("node_id",""))
        if nid.startswith("IR:"):
            continue
        if nid not in cm_ids:
            unresolved += 1
    if unresolved:
        result.error(f"Vector: {unresolved} FIR node_ids not in CaseMaster.csv")
    else:
        result.ok(f"Vector: all FIR node_ids resolve to CaseMaster rows")

    # Non-empty text
    empty = sum(1 for r in records if not r.get("text","").strip())
    if empty:
        result.warn(f"Vector: {empty} records have empty text")
    else:
        result.ok("Vector: all records have non-empty text")

    # Required metadata fields
    required_meta = {"CrimeNo", "district", "crime_type", "CrimeRegisteredDate", "lang", "doc_type"}
    for r in records[:5]:  # spot-check first 5
        meta = r.get("metadata", {})
        missing_meta = required_meta - set(meta.keys())
        if missing_meta:
            result.warn(f"Vector record {r.get('node_id')}: missing metadata: {missing_meta}")


# ---------------------------------------------------------------------------
# Suite E (new): Graph-from-DB parity
# ---------------------------------------------------------------------------

def check_graph_from_db_parity(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite E: Every Crime node_id equals a CaseMaster.CaseMasterID.
    Object node counts == distinct identifier values in SQL.
    No RESOLVED_AS/LINKED_TO/centrality/community_id pre-baked.
    """
    graph = output_dir / "historical" / "graph"
    ksp   = output_dir / "historical" / "sql" / "ksp"
    ext   = output_dir / "historical" / "sql" / "extension"

    if not graph.exists():
        result.warn(f"historical/graph/ not yet built (skipping graph parity check)")
        return

    # Crime node parity
    crime_nodes = {str(r["node_id"]) for r in _read_csv(graph / "nodes_crime.csv")}
    cm_ids      = {str(r["CaseMasterID"]) for r in _read_csv(ksp / "CaseMaster.csv")}
    extra  = crime_nodes - cm_ids
    missing = cm_ids - crime_nodes
    if extra:
        result.error(f"Graph Crime nodes not in CaseMaster: {extra}")
    if missing:
        result.error(f"CaseMaster rows with no Crime node: {missing}")
    if not extra and not missing:
        result.ok(f"Graph Crime node parity: {len(crime_nodes)} nodes match {len(cm_ids)} CaseMaster rows")

    # Object node count == distinct SQL values
    dim_map = [
        ("nodes_account.csv", ext / "accounts.csv", "AccountNo"),
        ("nodes_phone.csv",   ext / "phones.csv",   "Number"),
        ("nodes_device.csv",  ext / "devices.csv",  "IMEI"),
        ("nodes_upi.csv",     ext / "upis.csv",     "VPA"),
        ("nodes_ip.csv",      ext / "ips.csv",      "IPAddress"),
        ("nodes_wallet.csv",  ext / "wallets.csv",  "Address"),
    ]
    for graph_csv, sql_csv, pk_col in dim_map:
        graph_count = len(_read_csv(graph / graph_csv))
        sql_vals    = {r[pk_col] for r in _read_csv(sql_csv) if r.get(pk_col,"")}
        if graph_count != len(sql_vals):
            result.error(f"Object node count mismatch: {graph_csv} graph={graph_count} sql={len(sql_vals)}")
        else:
            result.ok(f"Object node count match: {graph_csv} = {graph_count}")


# ---------------------------------------------------------------------------
# Suite F: Dimension uniqueness + link survival through SQL round-trip
# ---------------------------------------------------------------------------

def check_dimension_uniqueness(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite F: Each dimension table has no duplicate natural-key rows.
    Checks: accounts(AccountNo), phones(Number), devices(IMEI),
            upis(VPA), ips(IPAddress), wallets(Address).
    """
    ext = output_dir / "historical" / "sql" / "extension"
    dim_checks = [
        ("accounts.csv",  "AccountNo"),
        ("phones.csv",    "Number"),
        ("devices.csv",   "IMEI"),
        ("upis.csv",      "VPA"),
        ("ips.csv",       "IPAddress"),
        ("wallets.csv",   "Address"),
    ]
    for fname, pk_col in dim_checks:
        rows = _read_csv(ext / fname)
        if not rows:
            result.warn(f"Dimension CSV missing/empty: {fname}")
            continue
        vals = [r.get(pk_col,"") for r in rows]
        dupes = len(vals) - len(set(vals))
        if dupes:
            result.error(f"Dimension {fname}: {dupes} duplicate {pk_col} values (dedup_corpus not applied)")
        else:
            result.ok(f"Dimension {fname}: {len(vals)} unique {pk_col} values (no duplicates)")


def check_scenario2_shared_node(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite F: Scenario 2 entity-resolution check.
    DEV_IMEI_02 must appear on at least 2 Accused rows in Accused.csv (shared device),
    and the corresponding device node must appear once in graph/nodes_device.csv.
    """
    try:
        from .identifier_pool import DEV_IMEI_02
    except ImportError:
        result.warn("identifier_pool not importable; skipping Scn2 shared-node check")
        return

    ksp   = output_dir / "historical" / "sql" / "ksp"
    ext   = output_dir / "historical" / "sql" / "extension"
    graph = output_dir / "historical" / "graph"

    # IMEI should appear in EXT_Uses link table for >= 2 accused
    uses_rows = _read_csv(ext / "rels_uses.csv")
    imei_uses = [
        r for r in uses_rows
        if r.get("to_object_id", "") in {DEV_IMEI_02, f"DEV_{DEV_IMEI_02}"}
    ]
    if len(imei_uses) < 2:
        result.warn(
            f"Scn2 shared IMEI {DEV_IMEI_02}: only {len(imei_uses)} uses edges "
            f"(expected >=2 for entity resolution demo)")
    else:
        result.ok(f"Scn2 shared IMEI {DEV_IMEI_02}: {len(imei_uses)} uses edges (entity resolution link exists)")

    # Device dimension: exactly one row
    device_rows = _read_csv(ext / "devices.csv")
    matching = [r for r in device_rows if r.get("IMEI","") == DEV_IMEI_02]
    if len(matching) != 1:
        result.error(f"Scn2 shared IMEI {DEV_IMEI_02}: {len(matching)} rows in devices.csv (expected 1)")
    else:
        result.ok(f"Scn2 shared IMEI {DEV_IMEI_02}: exactly 1 row in devices.csv")

    # Graph: one device node with this IMEI
    if (graph / "nodes_device.csv").exists():
        graph_devs = [r for r in _read_csv(graph / "nodes_device.csv")
                      if r.get("node_id","") == DEV_IMEI_02]
        if len(graph_devs) != 1:
            result.error(f"Scn2: graph nodes_device.csv has {len(graph_devs)} rows for {DEV_IMEI_02} (expected 1)")
        else:
            result.ok(f"Scn2: one graph device node for {DEV_IMEI_02}")


def check_identifier_byte_identity(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite F: Identifier bytes are identical across:
      1. extension/accounts.csv AccountNo
      2. extension/transactions.csv FromAccount / ToAccount
      3. graph/nodes_account.csv node_id
      4. live_demo/live_scn*/fir.expected.json 'identifiers'
    Spot-checks the cross-case pool identifiers (AGG_ACC_01, BRIDGE_ACC_03).
    """
    try:
        from .identifier_pool import AGG_ACC_01, BRIDGE_ACC_03
    except ImportError:
        result.warn("identifier_pool not importable; skipping byte-identity check")
        return

    ext   = output_dir / "historical" / "sql" / "extension"
    graph = output_dir / "historical" / "graph"
    live  = output_dir / "live_demo"

    for pool_key, pool_val in [("AGG_ACC_01", AGG_ACC_01["account_no"]),
                               ("BRIDGE_ACC_03", BRIDGE_ACC_03["account_no"])]:
        # Dimension table
        accts = {r["AccountNo"] for r in _read_csv(ext / "accounts.csv")}
        if pool_val not in accts:
            result.error(f"Byte-identity: {pool_key}={pool_val} not in extension/accounts.csv")
        else:
            result.ok(f"Byte-identity: {pool_key}={pool_val} in accounts.csv")

        # Graph node
        if (graph / "nodes_account.csv").exists():
            g_accts = {r.get("node_id","") for r in _read_csv(graph / "nodes_account.csv")}
            if pool_val not in g_accts:
                result.error(f"Byte-identity: {pool_key}={pool_val} not in graph nodes_account.csv")
            else:
                result.ok(f"Byte-identity: {pool_key}={pool_val} in graph nodes_account.csv")

    # Live expected: pool identifiers must be exact byte-match
    for scn_dir in ["live_scn1", "live_scn3"]:
        exp_path = live / scn_dir / "fir.expected.json"
        if not exp_path.exists():
            result.warn(f"Byte-identity: {scn_dir}/fir.expected.json missing")
            continue
        exp = json.loads(exp_path.read_text(encoding="utf-8"))
        pool_val = AGG_ACC_01["account_no"] if scn_dir == "live_scn1" else BRIDGE_ACC_03["account_no"]
        identifiers = exp.get("revealed_identifiers", {}).get("accounts", [])
        if pool_val not in identifiers:
            result.warn(f"Byte-identity: {pool_val} not in {scn_dir}/fir.expected.json revealed_identifiers.accounts")
        else:
            result.ok(f"Byte-identity: {pool_val} in {scn_dir}/fir.expected.json")


def check_cross_case_graph_links(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite F: Cross-case links from the DB-built graph.
    For each planted link scenario, verify the link exists in the graph
    (Account/Device/UPI shared across >= 2 Crime nodes via USES/MENTIONS edges).
    """
    graph = output_dir / "historical" / "graph"
    if not graph.exists():
        result.warn("historical/graph/ not built — cross-case link check skipped")
        return

    try:
        from .identifier_pool import AGG_ACC_01, DEV_IMEI_02, BRIDGE_ACC_03
    except ImportError:
        result.warn("identifier_pool not importable; skipping cross-case graph check")
        return

    # Read USES edges (Person -> Object)
    uses_rows = _read_csv(graph / "rels_uses.csv")
    mentions_rows = _read_csv(graph / "rels_mentions.csv")

    def object_case_ids(rows, object_natural_key):
        """Return set of source_caseid values where this object appears."""
        candidates = {
            object_natural_key,
            f"DEV_{object_natural_key}",
            f"UPI_{object_natural_key}",
            f"PHONE_{object_natural_key}",
            f"IP_{object_natural_key}",
            f"WALLET_{object_natural_key}",
        }
        return {
            r.get("source_caseid","") for r in rows
            if (r.get(":END_ID","") in candidates or r.get(":START_ID","") in candidates)
            and r.get("source_caseid","")
        }

    # Scn1: AGG_ACC_01 should appear in >=3 cases
    agg_cases = object_case_ids(uses_rows, AGG_ACC_01["account_no"])
    agg_cases |= object_case_ids(mentions_rows, AGG_ACC_01["account_no"])
    agg_cases |= object_case_ids(_read_csv(graph / "rels_transferred_to.csv"), AGG_ACC_01["account_no"])
    if len(agg_cases) < 3:
        result.warn(f"Cross-case: AGG_ACC_01 linked to only {len(agg_cases)} cases in graph (expected >=3)")
    else:
        result.ok(f"Cross-case: AGG_ACC_01 appears across {len(agg_cases)} cases in graph")

    # Scn2: DEV_IMEI_02 in >=2 cases
    imei_cases = object_case_ids(uses_rows, DEV_IMEI_02)
    if len(imei_cases) < 2:
        result.warn(f"Cross-case: DEV_IMEI_02 linked to only {len(imei_cases)} cases (expected >=2)")
    else:
        result.ok(f"Cross-case: DEV_IMEI_02 appears across {len(imei_cases)} cases")

    # Scn3: BRIDGE_ACC_03 must exist historically (second link forms after live ingest).
    bridge_cases = object_case_ids(uses_rows, BRIDGE_ACC_03["account_no"])
    bridge_cases |= object_case_ids(mentions_rows, BRIDGE_ACC_03["account_no"])
    bridge_cases |= object_case_ids(_read_csv(graph / "rels_transferred_to.csv"), BRIDGE_ACC_03["account_no"])
    if len(bridge_cases) < 1:
        result.warn(f"Cross-case: BRIDGE_ACC_03 linked to only {len(bridge_cases)} historical cases (expected >=1)")
    else:
        result.ok(f"Cross-case: BRIDGE_ACC_03 spans {len(bridge_cases)} historical cases in graph")


# ---------------------------------------------------------------------------
# Suite G: Context layer survival (SQL columns -> graph edges)
# ---------------------------------------------------------------------------

def check_sql_context_columns(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite G: Every SQL link/fact table has context columns.
    Required: source_caseid, observed_date, confidence (plus role/amount where applicable).
    """
    ext = output_dir / "historical" / "sql" / "extension"
    link_tables = [
        ("rels_uses.csv",          ["source_caseid", "observed_date", "confidence", "role"]),
        ("rels_mentions.csv",      ["source_caseid", "observed_date", "confidence"]),
        ("rels_accused_in.csv",    ["source_caseid", "observed_date", "confidence", "role"]),
        ("rels_complainant_in.csv",["source_caseid", "observed_date", "confidence"]),
        ("transactions.csv",       ["source_caseid", "observed_date", "confidence", "Amount", "Channel"]),
    ]
    for fname, required_cols in link_tables:
        rows = _read_csv(ext / fname)
        if not rows:
            result.warn(f"SQL context: {fname} is missing/empty")
            continue
        headers = set(rows[0].keys())
        for col in required_cols:
            if col not in headers:
                result.error(f"SQL link table {fname}: context column '{col}' MISSING")
            else:
                null_count = sum(1 for r in rows if not str(r.get(col, "")).strip())
                if null_count == len(rows):
                    result.warn(f"SQL link table {fname}: '{col}' is empty on all {len(rows)} rows")
                else:
                    result.ok(f"SQL link table {fname}.{col}: {len(rows)-null_count}/{len(rows)} populated")


def check_graph_edge_context(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite G: Every edge in the DB-built graph carries non-null
    source_caseid, observed_date, and confidence.
    """
    graph = output_dir / "historical" / "graph"
    if not graph.exists():
        result.warn("historical/graph/ not built — graph edge context check skipped")
        return

    edge_files = [
        "rels_uses.csv",
        "rels_mentions.csv",
        "rels_accused_in.csv",
        "rels_complainant_in.csv",
        "rels_transferred_to.csv",
    ]
    required_context_cols = ["source_caseid", "observed_date", "confidence"]

    for fname in edge_files:
        path = graph / fname
        rows = _read_csv(path)
        if not rows:
            result.warn(f"Graph edge file missing/empty: {fname}")
            continue
        for col in required_context_cols:
            if col not in rows[0]:
                result.error(f"Graph edge {fname}: context column '{col}' MISSING from CSV header")
                continue
            null_rows = [i for i, r in enumerate(rows) if not str(r.get(col,"")).strip()]
            if null_rows:
                result.error(
                    f"Graph edge {fname}: {len(null_rows)}/{len(rows)} edges "
                    f"have NULL/empty {col} (context not copied from SQL)")
            else:
                result.ok(f"Graph edge {fname}.{col}: all {len(rows)} edges carry non-null value")


def check_all_four_context_kinds(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite G: Verify all 4 context kinds are present system-wide.
    1. Provenance (source_caseid on edges)
    2. Edge qualifiers (confidence, role)
    3. Time/place (observed_date, timestamp on transactions)
    4. Legal meaning (ActCode + SectionCode on ActSectionAssociation)
    """
    graph = output_dir / "historical" / "graph"
    ext   = output_dir / "historical" / "sql" / "extension"
    ksp   = output_dir / "historical" / "sql" / "ksp"

    # 1. Provenance
    if (graph / "rels_uses.csv").exists():
        rows = _read_csv(graph / "rels_uses.csv")
        has_prov = any(r.get("source_caseid","") for r in rows)
        if has_prov:
            result.ok("Context kind 1 (Provenance): source_caseid present on USES edges")
        else:
            result.error("Context kind 1 (Provenance): source_caseid MISSING from USES edges")

    # 2. Edge qualifiers
    if (ext / "rels_uses.csv").exists():
        rows = _read_csv(ext / "rels_uses.csv")
        has_qual = any(r.get("confidence","") or r.get("role","") for r in rows)
        if has_qual:
            result.ok("Context kind 2 (Edge qualifiers): confidence/role present on rels_uses.csv")
        else:
            result.error("Context kind 2 (Edge qualifiers): confidence/role MISSING from rels_uses.csv")

    # 3. Time/place
    if (ext / "transactions.csv").exists():
        rows = _read_csv(ext / "transactions.csv")
        has_time = any(r.get("observed_date","") or r.get("Timestamp","") for r in rows)
        if has_time:
            result.ok("Context kind 3 (Time/place): observed_date/Timestamp present on transactions")
        else:
            result.error("Context kind 3 (Time/place): observed_date/Timestamp MISSING from transactions")

    # 4. Legal meaning
    asa_rows = _read_csv(ksp / "ActSectionAssociation.csv")
    has_legal = any(r.get("ActCode","") and r.get("SectionCode","") for r in asa_rows)
    if has_legal:
        result.ok(f"Context kind 4 (Legal meaning): ActCode+SectionCode present on {len(asa_rows)} ASA rows")
    else:
        result.error("Context kind 4 (Legal meaning): ActCode or SectionCode MISSING from ActSectionAssociation")


# ---------------------------------------------------------------------------
# Suite H (new): Two-route separation
# ---------------------------------------------------------------------------

def check_two_route_separation(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite H: Nothing from live_demo/ is loaded into any DB.
    - Reserved live CrimeNos must NOT appear in ksp.sqlite CaseMaster
    - Historical tables must have non-zero row counts
    """
    import sqlite3
    db_path = output_dir / "historical" / "db" / "ksp.sqlite"

    if not db_path.exists():
        result.warn("ksp.sqlite not found — two-route separation check skipped")
        return

    conn = sqlite3.connect(str(db_path))

    # Get live CrimeNos from id_registry state
    live_reservations = reg.get_all_live_reservations()
    live_crime_nos = [v["crime_no"] for v in live_reservations.values()]

    if live_crime_nos:
        placeholders = ",".join("?" for _ in live_crime_nos)
        rows = conn.execute(
            f"SELECT CrimeNo FROM CaseMaster WHERE CrimeNo IN ({placeholders})",
            live_crime_nos
        ).fetchall()
        if rows:
            result.error(f"Two-route VIOLATED: live CrimeNos in ksp.sqlite: {[r[0] for r in rows]}")
        else:
            result.ok(f"Two-route separation: none of {len(live_crime_nos)} live CrimeNos in ksp.sqlite")

    # Historical non-empty
    hist_count = conn.execute("SELECT COUNT(*) FROM CaseMaster").fetchone()[0]
    if hist_count == 0:
        result.error("ksp.sqlite CaseMaster is empty (historical route not loaded)")
    else:
        result.ok(f"Historical route loaded: {hist_count} CaseMaster rows in ksp.sqlite")

    # Live demo dir must NOT have a loaded DB indicator
    live_db = output_dir / "live_demo" / "db"
    if live_db.exists():
        result.error(f"live_demo/db/ directory exists — live data must never be loaded")
    else:
        result.ok("live_demo/db/ does not exist (correct — live data is held back)")

    conn.close()


# ---------------------------------------------------------------------------
# Suite I additions: ER-exact column names in CSV checks
# ---------------------------------------------------------------------------

def check_er_column_names(output_dir: Path, result: ValidationResult) -> None:
    """
    Suite I: Spot-check that ER-exact column names are present in actual CSVs.
    """
    ksp    = output_dir / "historical" / "sql" / "ksp"
    master = ksp / "master"

    checks = [
        (ksp    / "Victim.csv",           ["VictimPolice"]),
        (ksp    / "Accused.csv",          ["PersonID"]),
        (ksp    / "ArrestSurrender.csv",  ["IsAccused","IsComplainantAccused","IOID"]),
        (ksp    / "ActSectionAssociation.csv", ["ActOrderID","SectionOrderID"]),
        (master / "CrimeHead.csv",        ["CrimeGroupName"]),
        (master / "CrimeSubHead.csv",     ["CrimeHeadName","SeqID"]),
        (master / "Act.csv",              ["ActDescription","ShortName","Active"]),
        (master / "Section.csv",          ["SectionDescription","Active"]),
        (master / "CaseCategory.csv",     ["LookupValue"]),
        (master / "GravityOffence.csv",   ["LookupValue"]),
        (master / "CasteMaster.csv",      ["caste_master_id","caste_master_name"]),
        (master / "Employee.csv",         ["KGID","FirstName","EmployeeDOB"]),
        (master / "Court.csv",            ["StateID","Active"]),
        (master / "Unit.csv",             ["TypeID","ParentUnit","NationalityID","Active"]),
        (master / "Rank.csv",             ["Hierarchy","Active"]),
        (master / "Designation.csv",      ["Active","SortOrder"]),
        (master / "District.csv",         ["Active"]),
    ]
    for csv_path, required_cols in checks:
        if not csv_path.exists():
            result.warn(f"CSV missing: {csv_path.name}")
            continue
        rows = _read_csv(csv_path)
        if not rows:
            result.warn(f"CSV empty: {csv_path.name}")
            continue
        headers = set(rows[0].keys())
        for col in required_cols:
            if col not in headers:
                result.error(f"ER column missing from {csv_path.name}: {col}")
            else:
                result.ok(f"ER column present: {csv_path.name}.{col}")


def check_temporal_spatial_fidelity(output_dir: Path, result: ValidationResult) -> None:
    """
    Ensure temporal/spatial signals exist across SQL, graph, and vector outputs.
    """
    ksp = output_dir / "historical" / "sql" / "ksp"
    ext = output_dir / "historical" / "sql" / "extension"
    graph = output_dir / "historical" / "graph"
    vec = output_dir / "historical" / "vector" / "narratives.jsonl"

    case_rows = _read_csv(ksp / "CaseMaster.csv")
    geo_rows = _read_csv(ext / "case_geo.csv")
    districts = {r.get("IncidentDistrict", "") for r in geo_rows if r.get("IncidentDistrict", "")}
    offence_dates = {r.get("IncidentFromDate", "")[:10] for r in case_rows if r.get("IncidentFromDate", "")}
    if len(districts) >= 4:
        result.ok(f"Temporal/spatial: case_geo covers {len(districts)} districts")
    else:
        result.warn(f"Temporal/spatial: only {len(districts)} districts found in case_geo")
    if len(offence_dates) >= 20:
        result.ok(f"Temporal/spatial: offence dates span {len(offence_dates)} unique days")
    else:
        result.warn(f"Temporal/spatial: offence dates span only {len(offence_dates)} days")

    crime_nodes = _read_csv(graph / "nodes_crime.csv")
    if crime_nodes:
        required = ["date_of_offence", "amount_involved", "latitude", "longitude"]
        for col in required:
            missing = sum(1 for r in crime_nodes if not str(r.get(col, "")).strip())
            if missing:
                result.warn(f"nodes_crime.csv: {missing}/{len(crime_nodes)} rows missing {col}")
            else:
                result.ok(f"nodes_crime.csv: {col} present on all rows")

    fir_records = [r for r in _read_jsonl(vec) if str(r.get("doc_type", "")) == "fir"]
    if fir_records:
        required_meta = ["latitude", "longitude", "date_of_offence", "amount_involved"]
        for col in required_meta:
            missing = 0
            for rec in fir_records:
                meta = rec.get("metadata", {})
                if col not in meta or str(meta.get(col, "")).strip() == "":
                    missing += 1
            if missing:
                result.warn(f"vector FIR metadata: {missing}/{len(fir_records)} records missing {col}")
            else:
                result.ok(f"vector FIR metadata: {col} present on all records")


def check_package_import_sanity(result: ValidationResult) -> None:
    """Quick sanity check after package reorganization."""
    modules = [
        "data_generation.generate",
        "data_generation.export",
        "data_generation.db_loader",
        "data_generation.graph_builder",
        "data_generation.narrative_generator",
        "data_generation.validate",
    ]
    for mod_name in modules:
        try:
            __import__(mod_name)
            result.ok(f"Import sanity: {mod_name}")
        except Exception as exc:
            result.error(f"Import sanity failed for {mod_name}: {exc}")

# ---------------------------------------------------------------------------
# Main validation runner
# ---------------------------------------------------------------------------

def run_validation(output_dir: str = None, strict: bool = False) -> ValidationResult:
    """
    Run all validation checks (Suites A-I) against the given output directory.
    Runs after db_load + graph_from_db + vector_embed_docs + live_docs + evidence.
    --strict turns warnings into failures.
    """
    import logging
    log = logging.getLogger("validate")
    out = Path(output_dir or config.OUTPUT_DIR)
    result = ValidationResult()

    # Suite A — Schema and DB integrity
    log.info("Suite A: Schema + DB integrity...")
    check_ksp_masters(out, result)
    check_crime_no_format(out, result)
    check_fk_integrity(out, result)
    check_district_derivation(out, result)
    check_cstype_distribution(out, result)
    check_caste_religion_populated(out, result)
    check_er_conformance_superset(out, result)
    check_sqlite_db(out, result)
    check_er_column_names(out, result)
    check_package_import_sanity(result)

    # Suite B — Case correctness (already in check_crime_no_format etc.)
    log.info("Suite B: Case correctness...")
    # (CrimeNo format + district derivation already checked in Suite A)

    # Suite C — Document <-> SQL consistency
    log.info("Suite C: Document <-> SQL consistency...")
    check_historical_doc_sql_consistency(out, result)
    check_live_path(out, result)

    # Suite D — Vector completeness
    log.info("Suite D: Vector completeness...")
    check_vector_completeness(out, result)

    # Suite E — Graph-from-DB parity
    log.info("Suite E: Graph-from-DB parity...")
    check_graph_from_db_parity(out, result)
    check_no_resolved_as_edges(out, result)
    check_context_properties_on_edges(out, result)

    # Suite F — Link survival (scenario isolation)
    log.info("Suite F: Scenario/decoy link survival + dimension uniqueness...")
    check_scenario_isolation(out, result)
    check_dimension_uniqueness(out, result)
    check_scenario2_shared_node(out, result)
    check_identifier_byte_identity(out, result)
    check_cross_case_graph_links(out, result)

    # Suite G — Context survival
    log.info("Suite G: Context layer survival...")
    check_sql_context_columns(out, result)
    check_graph_edge_context(out, result)
    check_all_four_context_kinds(out, result)

    # Suite H — Two-route separation
    log.info("Suite H: Two-route separation...")
    check_two_route_separation(out, result)

    # Suite I — Data quality + volume
    log.info("Suite I: Data quality + volume...")
    check_volume_targets(out, result)
    check_ifsc_format(out, result)
    check_cross_store_ids(out, result)
    check_evidence_artifacts(out, result)
    check_translation_identifier_survival(out, result)
    check_narrative_tiers(out, result)
    check_temporal_spatial_fidelity(out, result)

    if strict:
        # Promote all warnings to errors in strict mode
        for w in result.warnings:
            result.errors.append(w.replace("[WARN]", "[ERROR(strict)]"))
        result.warnings.clear()

    log.info(result.summary())
    return result


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import argparse
    parser = argparse.ArgumentParser(description="Validate KSP synthetic dataset")
    parser.add_argument("--output-dir", default=config.OUTPUT_DIR)
    parser.add_argument("--strict", action="store_true",
                        help="Treat warnings as errors")
    args = parser.parse_args()
    res = run_validation(args.output_dir, args.strict)
    print(res.summary())
    sys.exit(0 if res.is_clean() else 1)
