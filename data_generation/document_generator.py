"""
document_generator.py - Generate full FIR document + Investigation Report for every
historical case under output/historical/docs/<CrimeNo>/.

Guarantees: every SQL field (KSP-core AND extension) and every identifier
(AccountNo, IMEI, VPA, Phone, IP, Wallet) appears verbatim in the document text.
This is the historical analogue of the live *.expected.json rule.

The structured SQL rows are "extracted from" these documents — the doc is the
primary, the SQL is the derivative.

Outputs per case:
  output/historical/docs/<CrimeNo>/fir.txt
  output/historical/docs/<CrimeNo>/fir.kn.txt   (Kannada, via Bedrock)
  output/historical/docs/<CrimeNo>/investigation_report.txt
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import ksp_master as km
from . import id_registry as reg
from .models import Corpus, FIR, Person, InvestigationReport

log = logging.getLogger("document_generator")


# ---------------------------------------------------------------------------
# FIR Header Block
# ---------------------------------------------------------------------------

def build_fir_header(crime_no: str, case_no: str, station_name: str,
                     district_name: str, registered_date: str,
                     incident_date: str, io_name: str,
                     complainant_name: str, complainant_age: int,
                     complainant_occupation: str, complainant_address: str,
                     accused_entries: List[Dict],
                     sections: List[Dict]) -> str:
    """
    Build the structured header block that mirrors a real KSP FIR document.
    All named values are sourced from SQL projection rows so they appear
    verbatim in the text.
    """
    sec_str = ", ".join(
        f"Section {s['SectionCode']} {s['ActCode']}" for s in sections
    ) or "Section 66D ITACT, Section 318 BNS"

    accused_lines = "\n".join(
        f"  {a.get('PersonID','A?')}. {a['AccusedName']} (Age: {a['AgeYear']}, Gender: {a['GenderID']})"
        for a in accused_entries
    ) or "  A1. Unknown (Age: -, Gender: -)"

    header = f"""KARNATAKA STATE POLICE
FIRST INFORMATION REPORT (FIR)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Crime No.        : {crime_no}
Case No.         : {case_no}
Police Station   : {station_name}
District         : {district_name}
Date Registered  : {registered_date}
Date of Offence  : {incident_date}
IO Officer       : {io_name}

COMPLAINANT DETAILS
-------------------
Name             : {complainant_name}
Age              : {complainant_age} years
Occupation       : {complainant_occupation}
Address          : {complainant_address}

ACCUSED DETAILS
---------------
{accused_lines}

SECTIONS CHARGED
----------------
{sec_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRIEF FACTS / COMPLAINT NARRATIVE
"""
    return header


# ---------------------------------------------------------------------------
# Identifier block builder
# ---------------------------------------------------------------------------

def _build_identifier_block(fir: FIR, proj: Dict) -> str:
    """
    Build a structured "Digital Evidence & Identifiers" section so that every
    account_no / IMEI / VPA / phone / IP / wallet appears verbatim in the doc.
    """
    parts = []
    ids = fir.identifiers_mentioned
    if ids.get("accounts"):
        parts.append("  Bank Accounts  : " + ", ".join(ids["accounts"]))
    if ids.get("imeis"):
        parts.append("  IMEI Numbers   : " + ", ".join(ids["imeis"]))
    if ids.get("upis"):
        parts.append("  UPI VPAs       : " + ", ".join(ids["upis"]))
    if ids.get("phones"):
        parts.append("  Phone Numbers  : " + ", ".join(ids["phones"]))
    if ids.get("ips"):
        parts.append("  IP Addresses   : " + ", ".join(ids["ips"]))
    if ids.get("wallets"):
        parts.append("  Crypto Wallets : " + ", ".join(ids["wallets"]))

    if not parts:
        return ""
    return "\nDIGITAL EVIDENCE AND IDENTIFIERS MENTIONED IN COMPLAINT\n" + "-" * 56 + "\n" + "\n".join(parts) + "\n"


def _build_transaction_block(fir: FIR, corpus: Corpus) -> str:
    """List transactions linked to this FIR so account_nos appear verbatim."""
    relevant = [t for t in corpus.transactions
                if t.source_fir_id == fir.fir_id or
                   (t.linked_fir_id and t.linked_fir_id == fir.fir_id)]
    if not relevant:
        return ""
    lines = ["", "FINANCIAL TRANSACTIONS REFERENCED IN COMPLAINT", "-" * 48]
    for t in relevant[:12]:  # cap at 12 to keep docs readable
        lines.append(
            f"  {t.timestamp[:10]}  |  From: {t.from_account}  ->  To: {t.to_account}"
            f"  |  Rs. {t.amount:,}  |  Channel: {t.channel}"
        )
    return "\n".join(lines) + "\n"


def _build_timeline_block(fir: FIR) -> str:
    """Structured dated sub-events for case-timeline reconstruction."""
    if not fir.sub_events:
        return ""
    lines = ["", "CASE TIMELINE (SUB-EVENTS)", "-" * 30]
    for ev in sorted(fir.sub_events, key=lambda e: e.timestamp):
        lines.append(f"  {ev.timestamp}  |  {ev.label}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Full FIR text builder
# ---------------------------------------------------------------------------

def build_fir_text(fir: FIR, corpus: Corpus, proj: Dict,
                   narrative: str, person_map: Dict[str, Person]) -> str:
    """Compose full fir.txt text."""
    cm = proj["case_master"]
    crime_no   = cm["CrimeNo"]
    case_no    = cm["CaseNo"]
    unit_id    = proj["unit_id"]
    unit_obj   = km.UNIT_MAP.get(unit_id)
    station_name = unit_obj.unit_name if unit_obj else str(unit_id)
    district_obj = km.DISTRICT_BY_ID.get(unit_obj.district_id if unit_obj else 0)
    district_name = district_obj.district_name if district_obj else "Karnataka"

    registered_date = cm["CrimeRegisteredDate"][:10]
    incident_date   = cm["IncidentFromDate"][:10]
    emp_id = cm["PolicePersonID"]
    emp_obj = next((e for e in km.EMPLOYEES if e.employee_id == emp_id), None)
    io_name = emp_obj.first_name if emp_obj else f"Employee-{emp_id}"

    comp = proj.get("complainant") or {}
    complainant_name  = comp.get("ComplainantName","")
    complainant_age   = comp.get("AgeYear", 0)
    occ_id = comp.get("OccupationID", 39)
    occ_obj = next((o for o in km.OCCUPATIONS if o.occupation_id == occ_id), None)
    complainant_occ   = occ_obj.occupation_name if occ_obj else "Other"
    complainant_addr  = comp.get("Address","Karnataka")

    accused_entries = proj.get("accused", [])
    asa_rows = proj.get("act_section_assocs", [])

    header = build_fir_header(
        crime_no, case_no, station_name, district_name,
        registered_date, incident_date, io_name,
        complainant_name, complainant_age, complainant_occ, complainant_addr,
        accused_entries, asa_rows,
    )

    id_block  = _build_identifier_block(fir, proj)
    txn_block = _build_transaction_block(fir, corpus)
    timeline_block = _build_timeline_block(fir)

    footer = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CaseMasterID     : {cm['CaseMasterID']}
PoliceStationID  : {unit_id}
CaseCategoryID   : {cm['CaseCategoryID']}
GravityOffenceID : {cm['GravityOffenceID']}
CrimeHeadID      : {cm['CrimeMajorHeadID']}
CrimeSubHeadID   : {cm['CrimeMinorHeadID']}
CaseStatusID     : {cm['CaseStatusID']}
CourtID          : {cm['CourtID']}
Lat/Long         : {cm['Latitude']}, {cm['Longitude']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Place, Date: {district_name}, {registered_date}
Signature of Complainant: {complainant_name}
Signature of Recording Officer: {io_name}, {station_name}
"""
    return header + narrative + id_block + timeline_block + txn_block + footer


# ---------------------------------------------------------------------------
# Full Investigation Report text builder
# ---------------------------------------------------------------------------

def build_ir_text(ir: InvestigationReport, fir: FIR, corpus: Corpus,
                  proj: Dict, ir_narrative: str,
                  person_map: Dict[str, Person]) -> str:
    cm = proj["case_master"]
    unit_id  = proj["unit_id"]
    unit_obj = km.UNIT_MAP.get(unit_id)
    station_name = unit_obj.unit_name if unit_obj else str(unit_id)
    dist_obj = km.DISTRICT_BY_ID.get(unit_obj.district_id if unit_obj else 0)
    district_name = dist_obj.district_name if dist_obj else "Karnataka"

    emp_id  = cm["PolicePersonID"]
    emp_obj = next((e for e in km.EMPLOYEES if e.employee_id == emp_id), None)
    io_name = emp_obj.first_name if emp_obj else f"Employee-{emp_id}"

    report_id = reg.get_report_id(ir.report_id) or "IR-?"

    # Accused names
    accused_names = ", ".join(
        a["AccusedName"] for a in proj.get("accused", [])
    ) or "Unknown"

    id_block  = _build_identifier_block(fir, proj)
    txn_block = _build_transaction_block(fir, corpus)
    timeline_block = _build_timeline_block(fir)

    header = f"""KARNATAKA STATE POLICE
INVESTIGATION REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Report ID        : IR:{report_id}
Crime No.        : {cm['CrimeNo']}
Case No.         : {cm['CaseNo']}
CaseMasterID     : {cm['CaseMasterID']}
Police Station   : {station_name}
District         : {district_name}
Report Date      : {ir.report_date}
IO Officer       : {io_name} (EmployeeID: {emp_id})
Accused          : {accused_names}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INVESTIGATION FINDINGS
"""
    # Seized items
    seized_str = ""
    if ir.seized_items:
        seized_str = "\nSEIZED ITEMS\n" + "-"*20 + "\n"
        seized_str += "\n".join(f"  - {item}" for item in ir.seized_items) + "\n"

    # Arrests
    arrest_str = ""
    if ir.arrests:
        arrest_str = "\nARRESTS MADE\n" + "-"*20 + "\n"
        arrest_str += "\n".join(f"  - {a}" for a in ir.arrests) + "\n"

    footer = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Place, Date: {district_name}, {ir.report_date}
Signature of IO: {io_name}, {station_name}
"""
    return header + ir_narrative + id_block + timeline_block + txn_block + seized_str + arrest_str + footer


# ---------------------------------------------------------------------------
# Main entry: generate docs for all historical cases
# ---------------------------------------------------------------------------

def generate_all_docs(corpus: Corpus, fir_projections: Dict[str, Dict],
                      narrative_map: Dict[str, str],
                      output_dir: str = "output/historical") -> Dict[str, str]:
    """
    Generate fir.txt + investigation_report.txt for every historical FIR.
    Returns {fir_id -> crime_no} mapping.
    """
    docs_root = Path(output_dir) / "docs"
    docs_root.mkdir(parents=True, exist_ok=True)

    person_map = {p.person_id: p for p in corpus.persons}
    ir_map: Dict[str, InvestigationReport] = {
        ir.fir_id: ir for ir in corpus.investigation_reports
    }

    fir_to_crimeno: Dict[str, str] = {}

    for fir in corpus.firs:
        proj = fir_projections.get(fir.fir_id)
        if proj is None:
            log.warning(f"No projection for FIR {fir.fir_id}, skipping doc generation")
            continue

        crime_no = proj["crime_no"]
        fir_to_crimeno[fir.fir_id] = crime_no
        case_dir = docs_root / crime_no
        case_dir.mkdir(parents=True, exist_ok=True)

        # English narrative
        narrative = narrative_map.get(fir.fir_id, fir.fir_id)

        # fir.txt
        fir_text = build_fir_text(fir, corpus, proj, narrative, person_map)
        (case_dir / "fir.txt").write_text(fir_text, encoding="utf-8")

        # Investigation Report (if exists)
        ir = ir_map.get(fir.fir_id)
        if ir:
            ir_narrative = narrative_map.get(ir.report_id, ir.money_trail_notes or "")
            ir_text = build_ir_text(ir, fir, corpus, proj, ir_narrative, person_map)
            (case_dir / "investigation_report.txt").write_text(ir_text, encoding="utf-8")
        else:
            # Create a minimal placeholder IR so every case has both docs
            _write_minimal_ir(case_dir, fir, proj, person_map)

        log.debug(f"Generated docs for {crime_no}")

    log.info(f"Generated docs for {len(fir_to_crimeno)} cases under {docs_root}")
    return fir_to_crimeno


def _write_minimal_ir(case_dir: Path, fir: FIR, proj: Dict,
                      person_map: Dict[str, Person]) -> None:
    """Write a minimal IR for cases without a full InvestigationReport object."""
    cm = proj["case_master"]
    unit_id  = proj["unit_id"]
    unit_obj = km.UNIT_MAP.get(unit_id)
    station_name = unit_obj.unit_name if unit_obj else str(unit_id)
    emp_id = cm["PolicePersonID"]
    emp_obj = next((e for e in km.EMPLOYEES if e.employee_id == emp_id), None)
    io_name = emp_obj.first_name if emp_obj else f"Employee-{emp_id}"

    text = f"""KARNATAKA STATE POLICE
INVESTIGATION REPORT (PRELIMINARY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Crime No.        : {cm['CrimeNo']}
Case No.         : {cm['CaseNo']}
CaseMasterID     : {cm['CaseMasterID']}
Police Station   : {station_name}
Report Date      : {fir.date_registered}
IO Officer       : {io_name} (EmployeeID: {emp_id})

Status           : Case under investigation. Preliminary enquiry completed.
                   Cyber Cell notified. Further investigation ongoing.

Signature: {io_name}, {station_name}
"""
    (case_dir / "investigation_report.txt").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Helper: verify all identifiers in FIR appear in fir.txt
# (called by validate.py Suite C)
# ---------------------------------------------------------------------------

def verify_doc_contains_identifiers(fir_txt_path: Path, fir: FIR,
                                    proj: Dict) -> List[str]:
    """
    Return list of identifiers NOT found verbatim in fir.txt.
    Empty list = PASS.
    """
    if not fir_txt_path.exists():
        return [f"fir.txt missing: {fir_txt_path}"]
    content = fir_txt_path.read_text(encoding="utf-8")
    missing = []

    # Check all identifiers_mentioned
    for id_type, id_list in fir.identifiers_mentioned.items():
        for val in id_list:
            if val and val not in content:
                missing.append(f"{id_type}:{val}")

    # Check core SQL fields
    cm = proj.get("case_master", {})
    for field_val in [cm.get("CrimeNo",""), cm.get("CaseNo",""),
                      str(cm.get("CaseMasterID",""))]:
        if field_val and field_val not in content:
            missing.append(f"SQL:{field_val}")

    comp = proj.get("complainant") or {}
    for field_val in [comp.get("ComplainantName","")]:
        if field_val and field_val not in content:
            missing.append(f"ComplainantName:{field_val}")

    for acc in proj.get("accused", []):
        if acc.get("AccusedName","") and acc["AccusedName"] not in content:
            missing.append(f"AccusedName:{acc['AccusedName']}")

    return missing
