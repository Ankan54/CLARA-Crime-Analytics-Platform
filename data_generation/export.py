"""
export.py - Registry-driven projection of Corpus -> KSP SQL core CSVs,
extension CSVs, graph Neo4j load files, and vector JSONL.

CSV column names are byte-faithful to Police_FIR_ER_Diagram.pdf for all
KSP-core/master tables. Extension tables are additive and segregated.

Output layout (under output.tmp/, renamed to output/ atomically on success):
  historical/
    sql/
      ksp/
        CaseMaster.csv  ComplainantDetails.csv  Victim.csv  Accused.csv
        ArrestSurrender.csv  ActSectionAssociation.csv  ChargesheetDetails.csv
        master/  (all KSP master tables)
      extension/
        accounts.csv  transactions.csv  phones.csv  devices.csv
        upis.csv  ips.csv  wallets.csv  case_geo.csv
        investigation_reports.csv  evidence.csv
        legal_elements.csv  evidence_types.csv  precedents.csv  ipc_sections.csv
        rels_uses.csv  rels_mentions.csv  rels_complainant_in.csv
        rels_accused_in.csv  rels_transferred_to.csv
    graph/
      nodes_crime.csv  nodes_person.csv  nodes_account.csv  nodes_phone.csv
      nodes_device.csv  nodes_upi.csv  nodes_ip.csv  nodes_wallet.csv
      nodes_section.csv  nodes_legal_element.csv  nodes_evidence_type.csv
      nodes_precedent.csv  nodes_evidence.csv  nodes_ipc_section.csv
      rels_*.csv  import.cypher
    vector/
      narratives.jsonl
  _SUCCESS
"""
from __future__ import annotations
import csv
import json
import os
import random
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config
from . import id_registry as reg
from . import ksp_master as km
from .legal_layer import (
    build_act_section_associations, reset_asa_counter,
    LEGAL_SECTIONS, LEGAL_ELEMENTS, EVIDENCE_TYPES, PRECEDENTS,
    IPC_SECTIONS, ELEMENT_SATISFIED_BY, LEGAL_SECTION_TO_KSP,
    REPLACES_EDGES, REQUIRES_EDGES, SATISFIED_BY_EDGES,
    SUPPORTS_EDGES, FAILED_ON_EDGES, INTERPRETS_EDGES,
    get_has_evidence_edges, get_charged_under_edges,
)
from .models import Corpus, FIR, Person, Account, Transaction, Phone, Device, UPI, IP, Wallet, InvestigationReport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

def _gender_code(gender: str) -> str:
    g = gender.strip().lower()
    if g in ("male", "m"):    return "M"
    if g in ("female", "f"):  return "F"
    return "T"

def _derive_district_name(unit_id: int) -> str:
    unit = km.UNIT_MAP.get(unit_id)
    if unit:
        dist = km.DISTRICT_BY_ID.get(unit.district_id)
        if dist:
            return dist.district_name
    return "Unknown"

# ---------------------------------------------------------------------------
# Master CSV writers  (ER-exact column names)
# ---------------------------------------------------------------------------

def write_masters(base: Path) -> None:
    master_dir = base / "sql" / "ksp" / "master"
    _mkdir(master_dir)

    # State  (ER: StateID, StateName, Active)
    _write_csv(master_dir / "State.csv",
        [{"StateID": km.STATE_ID_KARNATAKA, "StateName": km.STATE_NAME_KARNATAKA, "Active": 1}],
        ["StateID", "StateName", "Active"])

    # District  (ER: DistrictID, DistrictName, StateID, Active)
    _write_csv(master_dir / "District.csv",
        [{"DistrictID": d.district_id, "DistrictName": d.district_name,
          "StateID": d.state_id, "Active": d.active}
         for d in km.DISTRICTS],
        ["DistrictID", "DistrictName", "StateID", "Active"])

    # UnitType  (ER: UnitTypeID, UnitTypeName, CityDistState, Hierarchy, Active)
    _write_csv(master_dir / "UnitType.csv",
        [{"UnitTypeID": u.unit_type_id, "UnitTypeName": u.unit_type_name,
          "CityDistState": u.city_dist_state, "Hierarchy": u.hierarchy, "Active": u.active}
         for u in km.UNIT_TYPES],
        ["UnitTypeID", "UnitTypeName", "CityDistState", "Hierarchy", "Active"])

    # Unit  (ER: UnitID, UnitName, TypeID, ParentUnit, NationalityID, StateID, DistrictID, Active)
    _write_csv(master_dir / "Unit.csv",
        [{"UnitID": u.unit_id, "UnitName": u.unit_name, "TypeID": u.type_id,
          "ParentUnit": u.parent_unit or "", "NationalityID": u.nationality_id,
          "StateID": u.state_id, "DistrictID": u.district_id, "Active": u.active}
         for u in km.UNITS],
        ["UnitID", "UnitName", "TypeID", "ParentUnit", "NationalityID", "StateID", "DistrictID", "Active"])

    # Rank  (ER: RankID, RankName, Hierarchy, Active)
    _write_csv(master_dir / "Rank.csv",
        [{"RankID": r.rank_id, "RankName": r.rank_name,
          "Hierarchy": r.hierarchy, "Active": r.active}
         for r in km.RANKS],
        ["RankID", "RankName", "Hierarchy", "Active"])

    # Designation  (ER: DesignationID, DesignationName, Active, SortOrder)
    _write_csv(master_dir / "Designation.csv",
        [{"DesignationID": d.designation_id, "DesignationName": d.designation_name,
          "Active": d.active, "SortOrder": d.sort_order}
         for d in km.DESIGNATIONS],
        ["DesignationID", "DesignationName", "Active", "SortOrder"])

    # Employee  (ER: EmployeeID, DistrictID, UnitID, RankID, DesignationID, KGID,
    #              FirstName, EmployeeDOB, GenderID, BloodGroupID, PhysicallyChallenged, AppointmentDate)
    _write_csv(master_dir / "Employee.csv",
        [{"EmployeeID": e.employee_id, "DistrictID": e.district_id, "UnitID": e.unit_id,
          "RankID": e.rank_id, "DesignationID": e.designation_id,
          "KGID": e.kgid, "FirstName": e.first_name,
          "EmployeeDOB": e.employee_dob, "GenderID": e.gender_id,
          "BloodGroupID": e.blood_group_id,
          "PhysicallyChallenged": e.physically_challenged,
          "AppointmentDate": e.appointment_date}
         for e in km.EMPLOYEES],
        ["EmployeeID","DistrictID","UnitID","RankID","DesignationID","KGID","FirstName",
         "EmployeeDOB","GenderID","BloodGroupID","PhysicallyChallenged","AppointmentDate"])

    # Court  (ER: CourtID, CourtName, DistrictID, StateID, Active)
    _write_csv(master_dir / "Court.csv",
        [{"CourtID": c.court_id, "CourtName": c.court_name,
          "DistrictID": c.district_id, "StateID": c.state_id, "Active": c.active}
         for c in km.COURTS],
        ["CourtID", "CourtName", "DistrictID", "StateID", "Active"])

    # CaseCategory  (ER: CaseCategoryID, LookupValue)
    _write_csv(master_dir / "CaseCategory.csv",
        [{"CaseCategoryID": c.case_category_id, "LookupValue": c.lookup_value}
         for c in km.CASE_CATEGORIES],
        ["CaseCategoryID", "LookupValue"])

    # GravityOffence  (ER: GravityOffenceID, LookupValue)
    _write_csv(master_dir / "GravityOffence.csv",
        [{"GravityOffenceID": g.gravity_offence_id, "LookupValue": g.lookup_value}
         for g in km.GRAVITY_OFFENCES],
        ["GravityOffenceID", "LookupValue"])

    # CrimeHead  (ER: CrimeHeadID, CrimeGroupName, Active)
    _write_csv(master_dir / "CrimeHead.csv",
        [{"CrimeHeadID": h.crime_head_id, "CrimeGroupName": h.crime_group_name, "Active": h.active}
         for h in km.CRIME_HEADS],
        ["CrimeHeadID", "CrimeGroupName", "Active"])

    # CrimeSubHead  (ER: CrimeSubHeadID, CrimeHeadID, CrimeHeadName, SeqID, Active)
    # NOTE: crime_type_code is an internal helper field and is NOT exported to CSV
    _write_csv(master_dir / "CrimeSubHead.csv",
        [{"CrimeSubHeadID": s.crime_sub_head_id, "CrimeHeadID": s.crime_head_id,
          "CrimeHeadName": s.crime_head_name, "SeqID": s.seq_id, "Active": s.active}
         for s in km.CRIME_SUB_HEADS],
        ["CrimeSubHeadID", "CrimeHeadID", "CrimeHeadName", "SeqID", "Active"])

    # CrimeHeadActSection  (ER: CrimeHeadID, ActCode, SectionCode)
    _write_csv(master_dir / "CrimeHeadActSection.csv",
        [{"CrimeHeadID": l.crime_head_id, "ActCode": l.act_code, "SectionCode": l.section_code}
         for l in km.CRIME_HEAD_ACT_SECTIONS],
        ["CrimeHeadID", "ActCode", "SectionCode"])

    # CaseStatusMaster  (ER: CaseStatusID, CaseStatusName)
    _write_csv(master_dir / "CaseStatusMaster.csv",
        [{"CaseStatusID": s.case_status_id, "CaseStatusName": s.case_status_name}
         for s in km.CASE_STATUSES],
        ["CaseStatusID", "CaseStatusName"])

    # Act  (ER: ActCode, ActDescription, ShortName, Active)
    _write_csv(master_dir / "Act.csv",
        [{"ActCode": a.act_code, "ActDescription": a.act_description,
          "ShortName": a.short_name, "Active": a.active}
         for a in km.ACTS],
        ["ActCode", "ActDescription", "ShortName", "Active"])

    # Section  (ER: ActCode, SectionCode, SectionDescription, Active)
    _write_csv(master_dir / "Section.csv",
        [{"ActCode": s.act_code, "SectionCode": s.section_code,
          "SectionDescription": s.section_description, "Active": s.active}
         for s in km.SECTIONS],
        ["ActCode", "SectionCode", "SectionDescription", "Active"])

    # CasteMaster  (ER: caste_master_id, caste_master_name)
    _write_csv(master_dir / "CasteMaster.csv",
        [{"caste_master_id": c.caste_master_id, "caste_master_name": c.caste_master_name}
         for c in km.CASTES],
        ["caste_master_id", "caste_master_name"])

    # ReligionMaster  (ER: ReligionID, ReligionName)
    _write_csv(master_dir / "ReligionMaster.csv",
        [{"ReligionID": r.religion_id, "ReligionName": r.religion_name}
         for r in km.RELIGIONS],
        ["ReligionID", "ReligionName"])

    # OccupationMaster  (ER: OccupationID, OccupationName)
    _write_csv(master_dir / "OccupationMaster.csv",
        [{"OccupationID": o.occupation_id, "OccupationName": o.occupation_name}
         for o in km.OCCUPATIONS],
        ["OccupationID", "OccupationName"])

# ---------------------------------------------------------------------------
# Projector: FIR -> KSP-core rows  (ER-exact column names)
# ---------------------------------------------------------------------------

def _pick_cstype(rng: random.Random) -> str:
    roll = rng.random()
    cumulative = 0.0
    for cstype, prob in config.CSTYPE_DISTRIBUTION.items():
        cumulative += prob
        if roll < cumulative:
            return cstype
    return "C"

def _default_caste() -> int:
    return km.CASTE_MAP.get("General", 1)

def _default_religion() -> int:
    return km.RELIGION_MAP.get("Not Specified", 5)

_arrest_counter = 0

def project_fir(
    fir: FIR,
    persons: Dict[str, Person],
    rng: random.Random,
    year: int = 2026,
    category_code: int = config.CASE_CATEGORY_FIR,
) -> Dict[str, Any]:
    """
    Project a FIR into ER-exact KSP-core row dicts.
    Returns: case_master, complainant, victims, accused, arrest_surrenders,
             act_section_assocs, chargesheet, case_geo, crime_no, case_no, cm_id,
             unit_id, district_id.
    """
    global _arrest_counter
    station_id = fir.police_station
    if station_id not in km.STATION_ID_TO_UNIT_ID:
        station_id = "PS_BLR_CEN_01"
    unit_id = km.STATION_ID_TO_UNIT_ID.get(station_id, 1001)
    district_id = km.UNIT_MAP[unit_id].district_id

    cm_id = reg.case_master_id(fir.fir_id)
    crime_no = km.assign_crime_no(station_id, category_code, year)
    case_no = km.case_no_from_crime_no(crime_no)

    employee_id = km.IO_NAME_TO_EMPLOYEE_ID.get(
        fir.io_officer, km.get_default_employee_id(station_id))
    court_id = km.get_default_court_id(station_id)
    status_id = km.CASE_STATUS_MAP.get(fir.status,
                km.CASE_STATUS_MAP.get("Under Investigation", 1))
    major_head_id = km.CRIME_TYPE_TO_HEAD_ID.get(fir.crime_type, 101)
    minor_head_id = km.CRIME_TYPE_TO_SUB_HEAD_ID.get(fir.crime_type, 1011)

    # CaseMaster  (ER-exact columns)
    case_master_row = {
        "CaseMasterID":        cm_id,
        "CrimeNo":             crime_no,
        "CaseNo":              case_no,
        "CrimeRegisteredDate": fir.date_registered + "T09:00:00",
        "PolicePersonID":      employee_id,
        "PoliceStationID":     unit_id,
        "CaseCategoryID":      category_code,
        "GravityOffenceID":    km.DEFAULT_GRAVITY_ID,
        "CrimeMajorHeadID":    major_head_id,
        "CrimeMinorHeadID":    minor_head_id,
        "CaseStatusID":        status_id,
        "CourtID":             court_id,
        "IncidentFromDate":    fir.date_of_offence + "T00:00:00",
        "IncidentToDate":      fir.date_of_offence + "T23:59:00",
        "InfoReceivedPSDate":  fir.date_registered + "T09:00:00",
        "Latitude":            fir.lat,
        "Longitude":           fir.long,
        "BriefFacts":          "",  # filled from narrative_map by caller
    }

    # ComplainantDetails  (ER-exact columns)
    comp_person = persons.get(fir.complainant_person_id)
    complainant_row = None
    if comp_person:
        comp_id = reg.complainant_id(fir.complainant_person_id)
        complainant_row = {
            "ComplainantID":   comp_id,
            "CaseMasterID":    cm_id,
            "ComplainantName": comp_person.full_name,
            "AgeYear":         comp_person.age,
            "GenderID":        _gender_code(comp_person.gender),
            "OccupationID":    km.get_occupation_id(comp_person.occupation),
            "CasteID":         _default_caste(),
            "ReligionID":      _default_religion(),
            "Address":         comp_person.address,
        }

    # Victim  (ER-exact: VictimMasterID, CaseMasterID, VictimName, AgeYear, GenderID, VictimPolice)
    victim_rows = []
    if comp_person:
        vm_id = reg.victim_master_id(fir.complainant_person_id + "_v")
        victim_rows.append({
            "VictimMasterID": vm_id,
            "CaseMasterID":   cm_id,
            "VictimName":     comp_person.full_name,
            "AgeYear":        comp_person.age,
            "GenderID":       _gender_code(comp_person.gender),
            "VictimPolice":   employee_id,  # ER column VictimPolice = FK -> Employee
        })

    # Accused  (ER-exact: AccusedMasterID, CaseMasterID, AccusedName, AgeYear, GenderID, PersonID)
    accused_rows = []
    arrest_rows = []
    for idx, acc_pid in enumerate(fir.accused_person_ids, start=1):
        acc_person = persons.get(acc_pid)
        if acc_person is None:
            continue
        acc_id = reg.accused_master_id(acc_pid)
        accused_rows.append({
            "AccusedMasterID": acc_id,
            "CaseMasterID":    cm_id,
            "PersonID":        f"A{idx}",   # ER column PersonID (VARCHAR label)
            "AccusedName":     acc_person.full_name,
            "AgeYear":         acc_person.age,
            "GenderID":        _gender_code(acc_person.gender),
        })
        # ArrestSurrender  (ER-exact: all 12 columns)
        if acc_person.role != "controller":
            _arrest_counter += 1
            arrest_rows.append({
                "ArrestSurrenderID":         _arrest_counter,
                "CaseMasterID":              cm_id,
                "ArrestSurrenderTypeID":     1,           # 1=Arrest
                "ArrestSurrenderDate":       fir.date_registered,
                "ArrestSurrenderStateId":    km.STATE_ID_KARNATAKA,
                "ArrestSurrenderDistrictId": district_id,
                "PoliceStationID":           unit_id,
                "IOID":                      employee_id,
                "CourtID":                   court_id,
                "AccusedMasterID":           acc_id,
                "IsAccused":                 1,
                "IsComplainantAccused":      0,
            })

    # ActSectionAssociation  (ER-exact composite key; no ASAID surrogate)
    # Columns: CaseMasterID, ActCode, SectionCode, ActOrderID, SectionOrderID
    asa_rows = []
    sections = km.CRIME_TYPE_SECTIONS.get(fir.crime_type,
               [("ITACT","66D"), ("BNS","318")])
    # Group by ActCode to assign ActOrderID
    act_order: Dict[str, int] = {}
    for act_code, section_code in sections:
        if act_code not in act_order:
            act_order[act_code] = len(act_order) + 1
        sec_order = sum(1 for a, s in sections if a == act_code and
                        sections.index((a, s)) <= sections.index((act_code, section_code)))
        asa_rows.append({
            "CaseMasterID":    cm_id,
            "ActCode":         act_code,
            "SectionCode":     section_code,
            "ActOrderID":      act_order[act_code],
            "SectionOrderID":  sec_order,
        })

    # ChargesheetDetails  (ER: ChargesheetID is CSID in our internal name)
    cs_counter = getattr(project_fir, "_cs_counter", 0) + 1
    project_fir._cs_counter = cs_counter
    cstype = _pick_cstype(rng)
    chargesheet_row = {
        "CSID":           cs_counter,
        "CaseMasterID":   cm_id,
        "CSDate":         fir.date_registered if cstype == "A" else "",
        "CSType":         cstype,
        "PolicePersonID": employee_id,
    }

    # CaseGeo  (extension: pincode; NOT on CaseMaster per ER)
    geo_id = reg.ext_obj_id(fir.fir_id + "_geo")
    pincode = getattr(fir, "pincode", "") or ""
    case_geo_row = {
        "GeoID":           geo_id,
        "CaseMasterID":    cm_id,
        "Pincode":         pincode,
        "IncidentDistrict":fir.district,
    }

    return {
        "case_master":         case_master_row,
        "complainant":         complainant_row,
        "victims":             victim_rows,
        "accused":             accused_rows,
        "arrest_surrenders":   arrest_rows,
        "act_section_assocs":  asa_rows,
        "chargesheet":         chargesheet_row,
        "case_geo":            case_geo_row,
        "crime_no":            crime_no,
        "case_no":             case_no,
        "cm_id":               cm_id,
        "unit_id":             unit_id,
        "district_id":         district_id,
    }

# ---------------------------------------------------------------------------
# KSP SQL core CSV writers  (ER-exact column sets)
# ---------------------------------------------------------------------------

def write_ksp_core_csvs(base: Path, fir_projections: Dict[str, Dict]) -> None:
    ksp = base / "sql" / "ksp"
    _mkdir(ksp)

    case_masters, complainants, victims_list = [], [], []
    accused_list, arrest_list, asa_list, chargesheet_list = [], [], [], []

    for fir_id, proj in fir_projections.items():
        case_masters.append(proj["case_master"])
        if proj["complainant"]:
            complainants.append(proj["complainant"])
        victims_list.extend(proj["victims"])
        accused_list.extend(proj["accused"])
        arrest_list.extend(proj.get("arrest_surrenders", []))
        asa_list.extend(proj["act_section_assocs"])
        chargesheet_list.append(proj["chargesheet"])

    # CaseMaster
    _write_csv(ksp / "CaseMaster.csv", case_masters,
        ["CaseMasterID","CrimeNo","CaseNo","CrimeRegisteredDate",
         "PolicePersonID","PoliceStationID","CaseCategoryID","GravityOffenceID",
         "CrimeMajorHeadID","CrimeMinorHeadID","CaseStatusID","CourtID",
         "IncidentFromDate","IncidentToDate","InfoReceivedPSDate",
         "Latitude","Longitude","BriefFacts"])

    # ComplainantDetails  (ER columns)
    _write_csv(ksp / "ComplainantDetails.csv", complainants,
        ["ComplainantID","CaseMasterID","ComplainantName","AgeYear","GenderID",
         "OccupationID","CasteID","ReligionID","Address"])

    # Victim  (ER-exact: VictimMasterID, CaseMasterID, VictimName, AgeYear, GenderID, VictimPolice)
    _write_csv(ksp / "Victim.csv", victims_list,
        ["VictimMasterID","CaseMasterID","VictimName","AgeYear","GenderID","VictimPolice"])

    # Accused  (ER-exact: AccusedMasterID, CaseMasterID, AccusedName, AgeYear, GenderID, PersonID)
    _write_csv(ksp / "Accused.csv", accused_list,
        ["AccusedMasterID","CaseMasterID","PersonID","AccusedName","AgeYear","GenderID"])

    # ArrestSurrender  (ER-exact: all 12 columns)
    _write_csv(ksp / "ArrestSurrender.csv", arrest_list,
        ["ArrestSurrenderID","CaseMasterID","ArrestSurrenderTypeID","ArrestSurrenderDate",
         "ArrestSurrenderStateId","ArrestSurrenderDistrictId","PoliceStationID","IOID",
         "CourtID","AccusedMasterID","IsAccused","IsComplainantAccused"])

    # ActSectionAssociation  (ER composite key; no ASAID)
    _write_csv(ksp / "ActSectionAssociation.csv", asa_list,
        ["CaseMasterID","ActCode","SectionCode","ActOrderID","SectionOrderID"])

    # ChargesheetDetails
    _write_csv(ksp / "ChargesheetDetails.csv", chargesheet_list,
        ["CSID","CaseMasterID","CSDate","CSType","PolicePersonID"])

# ---------------------------------------------------------------------------
# Extension CSV writers  (dimension + fact tables; context columns on link tables)
# ---------------------------------------------------------------------------

def write_extension_csvs(base: Path, corpus: Corpus,
                         fir_projections: Dict[str, Dict]) -> None:
    ext = base / "sql" / "extension"
    _mkdir(ext)

    # Compute last inbound / last outbound timestamps per account.
    last_inbound: Dict[str, str] = {}
    last_outbound: Dict[str, str] = {}

    def _set_max(target: Dict[str, str], key: str, value: str) -> None:
        if not key or not value:
            return
        if key not in target or value > target[key]:
            target[key] = value

    for t in corpus.transactions:
        _set_max(last_outbound, t.from_account, t.timestamp)
        _set_max(last_inbound, t.to_account, t.timestamp)
    for a in corpus.accounts:
        for ev in a.activity_history:
            ts = ev.get("timestamp", "")
            direction = (ev.get("direction", "") or "").lower()
            if direction == "in":
                _set_max(last_inbound, a.account_no, ts)
            elif direction == "out":
                _set_max(last_outbound, a.account_no, ts)

    # Dimension tables — one row per unique identifier value
    _write_csv(ext / "accounts.csv",
        [{"AccountNo": a.account_no, "Bank": a.bank, "IFSC": a.ifsc,
          "BranchDistrict": a.branch_district, "AccountType": a.account_type,
          "OpenDate": a.open_date, "KYCName": a.kyc_name,
          "IsFlaggedMule": int(a.is_flagged_mule),
          "LastInbound": last_inbound.get(a.account_no, ""),
          "LastOutbound": last_outbound.get(a.account_no, "")}
         for a in corpus.accounts],
        ["AccountNo","Bank","IFSC","BranchDistrict","AccountType",
         "OpenDate","KYCName","IsFlaggedMule","LastInbound","LastOutbound"])

    _write_csv(ext / "phones.csv",
        [{"Number": p.number, "PhoneID": p.phone_id} for p in corpus.phones],
        ["Number","PhoneID"])

    _write_csv(ext / "devices.csv",
        [{"IMEI": d.imei, "DeviceID": d.device_id} for d in corpus.devices],
        ["IMEI","DeviceID"])

    _write_csv(ext / "upis.csv",
        [{"VPA": u.vpa, "UPIID": u.upi_id} for u in corpus.upis],
        ["VPA","UPIID"])

    _write_csv(ext / "ips.csv",
        [{"IPAddress": ip.ip_address, "IPID": ip.ip_id,
          "GeoLat": ip.geolocation.get("lat",""),
          "GeoLong": ip.geolocation.get("long",""),
          "GeoCity": ip.geolocation.get("city","")}
         for ip in corpus.ips],
        ["IPAddress","IPID","GeoLat","GeoLong","GeoCity"])

    _write_csv(ext / "wallets.csv",
        [{"Address": w.address, "WalletID": w.wallet_id, "Chain": w.chain}
         for w in corpus.wallets],
        ["Address","WalletID","Chain"])

    # Transactions  (fact table: FK to accounts by natural key + context columns)
    txn_rows = []
    for t in corpus.transactions:
        src_cm_id = reg.resolve_source_fir_id(t.source_fir_id) or ""
        txn_rows.append({
            "TxnID":        t.txn_id,
            "FromAccount":  t.from_account,
            "ToAccount":    t.to_account,
            "Amount":       t.amount,
            "Timestamp":    t.timestamp,
            "Channel":      t.channel,
            "HopRole":      t.hop_role,
            # Context columns
            "CaseMasterID":    src_cm_id,
            "source_caseid":   src_cm_id,
            "observed_date":   t.timestamp[:10] if t.timestamp else "",
            "confidence":      1.0,
            "role":            t.hop_role,
        })
    _write_csv(ext / "transactions.csv", txn_rows,
        ["TxnID","FromAccount","ToAccount","Amount","Timestamp","Channel","HopRole",
         "CaseMasterID","source_caseid","observed_date","confidence","role"])

    # USES edges (link table: Accused -> identifier Object; with context columns)
    uses_rows = []
    for e in corpus.uses_edges:
        src_cm = reg.resolve_source_fir_id(e.get("source_fir_id","")) or e.get("source_fir_id","")
        uses_rows.append({
            "from_person_id": e["from_person_id"],
            "to_object_id":   e["to_object_id"],
            "object_type":    e.get("object_type",""),
            "source_caseid":  src_cm,
            "observed_date":  e.get("observed_date",""),
            "confidence":     e.get("confidence", 1.0),
            "role":           e.get("role","") or e.get("object_type", "").lower(),
        })
    _write_csv(ext / "rels_uses.csv", uses_rows,
        ["from_person_id","to_object_id","object_type",
         "source_caseid","observed_date","confidence","role"])

    # MENTIONS edges (CaseMaster -> identifier; with context columns)
    mentions_rows = []
    for fir in corpus.firs:
        cm_id = reg.get_case_master_id(fir.fir_id)
        if cm_id is None:
            continue
        for obj_type, obj_ids in fir.identifiers_mentioned.items():
            for oid in obj_ids:
                mentions_rows.append({
                    "case_master_id": cm_id,
                    "object_id":      oid,
                    "object_type":    obj_type,
                    "source_caseid":  cm_id,
                    "observed_date":  fir.date_registered,
                    "confidence":     1.0,
                })
    _write_csv(ext / "rels_mentions.csv", mentions_rows,
        ["case_master_id","object_id","object_type",
         "source_caseid","observed_date","confidence"])

    # ACCUSED_IN link table (with context columns)
    acc_in_rows = []
    for fir in corpus.firs:
        cm_id = reg.get_case_master_id(fir.fir_id)
        if cm_id is None:
            continue
        for acc_pid in fir.accused_person_ids:
            acc_id = reg.get_accused_master_id(acc_pid)
            if acc_id:
                acc_in_rows.append({
                    "AccusedMasterID": acc_id,
                    "CaseMasterID":    cm_id,
                    "source_caseid":   cm_id,
                    "observed_date":   fir.date_registered,
                    "confidence":      1.0,
                    "role":            "accused",
                })
    _write_csv(ext / "rels_accused_in.csv", acc_in_rows,
        ["AccusedMasterID","CaseMasterID","source_caseid","observed_date","confidence","role"])

    # COMPLAINANT_IN link table (with context columns)
    comp_in_rows = []
    for fir in corpus.firs:
        cm_id = reg.get_case_master_id(fir.fir_id)
        if cm_id is None:
            continue
        comp_id = reg.get_complainant_id(fir.complainant_person_id)
        if comp_id:
            comp_in_rows.append({
                "ComplainantID": comp_id,
                "CaseMasterID":  cm_id,
                "source_caseid": cm_id,
                "observed_date": fir.date_registered,
                "confidence":    1.0,
            })
    _write_csv(ext / "rels_complainant_in.csv", comp_in_rows,
        ["ComplainantID","CaseMasterID","source_caseid","observed_date","confidence"])

    # CaseGeo
    geo_rows = [v["case_geo"] for v in fir_projections.values() if v.get("case_geo")]
    if geo_rows:
        _write_csv(ext / "case_geo.csv", geo_rows,
            ["GeoID","CaseMasterID","Pincode","IncidentDistrict"])

    # InvestigationReport
    ir_rows = []
    for ir in corpus.investigation_reports:
        cm_id = reg.resolve_source_fir_id(ir.fir_id) or reg.case_master_id(ir.fir_id)
        ir_rows.append({
            "ReportID":         reg.report_id(ir.report_id),
            "CaseMasterID":     cm_id,
            "ReportDate":       ir.report_date,
            "IOOfficer":        ir.io_officer,
            "MoneyTrailNotes":  ir.money_trail_notes,
            "LinkedIdentifiers":json.dumps(ir.newly_linked_identifiers),
            "SeizedItems":      json.dumps(ir.seized_items),
            "Arrests":          json.dumps(ir.arrests),
            "IsLive":           int(ir.is_live),
        })
    _write_csv(ext / "investigation_reports.csv", ir_rows,
        ["ReportID","CaseMasterID","ReportDate","IOOfficer",
         "MoneyTrailNotes","LinkedIdentifiers","SeizedItems","Arrests","IsLive"])

    # Evidence — minimal document-anchored rows (not the BSA-63 legal-checklist
    # subsystem in legal_layer.py, which stays unwired/out of scope). Historical
    # cases previously had zero Evidence rows anywhere downstream, so their
    # graph shape was Case-[:MENTIONS]->Account directly instead of
    # Case-[:HAS_EVIDENCE]->Evidence-[:MENTIONS]->Account like live-ingested
    # cases -- this gives every historical case one Evidence row for its FIR
    # (always present) and one for its IR (where an IR exists), anchored to
    # the actual on-disk document so file_ref is real, not synthetic.
    evidence_rows: List[Dict[str, Any]] = []
    evidence_seq = 0
    for fir in corpus.firs:
        cm_id = reg.get_case_master_id(fir.fir_id)
        if cm_id is None:
            continue
        proj = fir_projections.get(fir.fir_id) or {}
        crime_no = proj.get("crime_no") or (proj.get("case_master") or {}).get("CrimeNo")
        if not crime_no:
            continue
        evidence_seq += 1
        evidence_rows.append({
            "EvidenceID": evidence_seq,
            "CaseMasterID": cm_id,
            "DocType": "FIR",
            "FileRef": f"historical/docs/{crime_no}/fir.txt",
            "OriginalFilename": "fir.txt",
            "ExtractionStatus": "success",
        })

    for ir in corpus.investigation_reports:
        if ir.is_live:
            continue
        cm_id = reg.resolve_source_fir_id(ir.fir_id) or reg.case_master_id(ir.fir_id)
        if cm_id is None:
            continue
        proj = fir_projections.get(ir.fir_id) or {}
        crime_no = proj.get("crime_no") or (proj.get("case_master") or {}).get("CrimeNo")
        if not crime_no:
            continue
        evidence_seq += 1
        evidence_rows.append({
            "EvidenceID": evidence_seq,
            "CaseMasterID": cm_id,
            "DocType": "IR",
            "FileRef": f"historical/docs/{crime_no}/investigation_report.txt",
            "OriginalFilename": "investigation_report.txt",
            "ExtractionStatus": "success",
        })

    _write_csv(ext / "evidence.csv", evidence_rows,
        ["EvidenceID","CaseMasterID","DocType","FileRef","OriginalFilename","ExtractionStatus"])

    # Victim / Accused detail extension rows
    fir_map = {f.fir_id: f for f in corpus.firs}
    person_map = {p.person_id: p for p in corpus.persons}
    victim_detail_rows: List[Dict[str, Any]] = []
    accused_detail_rows: List[Dict[str, Any]] = []
    subevent_rows: List[Dict[str, Any]] = []
    subevent_counter = 0
    for fir_id, proj in fir_projections.items():
        fir = fir_map.get(fir_id)
        if fir is None:
            continue
        cm_id = proj.get("cm_id") or reg.get_case_master_id(fir_id)

        for v in proj.get("victims", []):
            victim_person = person_map.get(fir.complainant_person_id)
            victim_detail_rows.append({
                "VictimMasterID": v["VictimMasterID"],
                "OccupationID": km.get_occupation_id(victim_person.occupation) if victim_person else "",
                "CasteID": _default_caste(),
                "ReligionID": _default_religion(),
                "Address": victim_person.address if victim_person else "",
                "Mobile": "",
                "LossAmount": fir.amount_involved,
                "ResidenceDistrict": victim_person.district if victim_person else fir.district,
            })

        accused_person_ids = fir.accused_person_ids
        for idx, acc in enumerate(proj.get("accused", [])):
            person = person_map.get(accused_person_ids[idx]) if idx < len(accused_person_ids) else None
            accused_detail_rows.append({
                "AccusedMasterID": acc["AccusedMasterID"],
                "OccupationID": km.get_occupation_id(person.occupation) if person else "",
                "CasteID": _default_caste(),
                "ReligionID": _default_religion(),
                "Address": person.address if person else "Unknown",
                "IsArrested": 0,   # historical FIRs — no arrest before live demo
                "ResidenceDistrict": person.district if person else fir.district,
            })

        for ev in fir.sub_events:
            subevent_counter += 1
            subevent_rows.append({
                "SubEventID": subevent_counter,
                "CaseMasterID": cm_id,
                "Label": ev.label,
                "Timestamp": ev.timestamp,
                "source_caseid": cm_id,
                "observed_date": ev.timestamp[:10] if ev.timestamp else "",
                "confidence": 1.0,
            })

    _write_csv(ext / "victim_details.csv", victim_detail_rows,
        ["VictimMasterID","OccupationID","CasteID","ReligionID",
         "Address","Mobile","LossAmount","ResidenceDistrict"])
    _write_csv(ext / "accused_details.csv", accused_detail_rows,
        ["AccusedMasterID","OccupationID","CasteID","ReligionID",
         "Address","IsArrested","ResidenceDistrict"])
    _write_csv(ext / "sub_events.csv", subevent_rows,
        ["SubEventID","CaseMasterID","Label","Timestamp",
         "source_caseid","observed_date","confidence"])

    # Legal extension tables
    _write_csv(ext / "legal_elements.csv",
        [{"ElementID": e.element_id, "SectionID": e.section_id,
          "Name": e.name, "Description": e.description}
         for e in LEGAL_ELEMENTS],
        ["ElementID","SectionID","Name","Description"])
    _write_csv(ext / "evidence_types.csv",
        [{"EvidenceTypeID": e.evidence_type_id, "Name": e.name,
          "Description": e.description, "Requires63Certificate": int(e.requires_63_certificate)}
         for e in EVIDENCE_TYPES],
        ["EvidenceTypeID","Name","Description","Requires63Certificate"])
    _write_csv(ext / "precedents.csv",
        [{"PrecedentID": p.precedent_id, "CaseName": p.case_name,
          "Citation": p.citation, "Year": p.year, "Court": p.court,
          "Outcome": p.outcome, "ElementTurnedOn": p.element_turned_on,
          "SectionID": p.section_id, "HoldingSummary": p.holding_summary,
          "IsOverruled": int(p.is_overruled)}
         for p in PRECEDENTS],
        ["PrecedentID","CaseName","Citation","Year","Court","Outcome",
         "ElementTurnedOn","SectionID","HoldingSummary","IsOverruled"])
    # Bridges (ActCode, SectionCode) -> the legal layer's SectionID, straight from
    # LEGAL_SECTION_TO_KSP -- the same mapping build_act_section_associations() uses to
    # emit the charges in the first place, so the two can't drift apart.
    _write_csv(ext / "section_map.csv",
        [{"ActCode": act_code, "SectionCode": section_code, "SectionID": section_id}
         for section_id, (act_code, section_code) in LEGAL_SECTION_TO_KSP.items()],
        ["ActCode","SectionCode","SectionID"])
    _write_csv(ext / "element_satisfied_by.csv",
        [{"ElementID": r["element_id"], "EvidenceTypeID": r["evidence_type_id"]}
         for r in ELEMENT_SATISFIED_BY],
        ["ElementID","EvidenceTypeID"])
    _write_csv(ext / "ipc_sections.csv",
        [{"IPCSectionID": s.ipc_section_id, "SectionNumber": s.section_number,
          "Title": s.title}
         for s in IPC_SECTIONS],
        ["IPCSectionID","SectionNumber","Title"])

# ---------------------------------------------------------------------------
# Graph node / relationship writers
# (Note: graph_builder.py will supersede this for the DB-sourced build;
#  this writer is kept for the in-memory staging pass during export.)
# ---------------------------------------------------------------------------

def write_graph(base: Path, corpus: Corpus,
                fir_projections: Dict[str, Dict],
                narrative_map: Dict[str, str]) -> None:
    graph = base / "graph"
    _mkdir(graph)

    # nodes_crime.csv
    crime_rows = []
    for fir in corpus.firs:
        cm_id = reg.get_case_master_id(fir.fir_id)
        if cm_id is None:
            continue
        proj = fir_projections.get(fir.fir_id, {})
        crime_rows.append({
            "node_id":        cm_id,
            "crime_no":       proj.get("crime_no",""),
            "case_no":        proj.get("case_no",""),
            "crime_type":     fir.crime_type,
            "district_id":    proj.get("district_id",0),
            "district_name":  _derive_district_name(proj.get("unit_id",1001)),
            "registered_date":fir.date_registered,
            "status":         proj.get("case_master",{}).get("CaseStatusID",""),
            "amount_involved":fir.amount_involved,
            "vector_id":      cm_id,
        })
    _write_csv(graph / "nodes_crime.csv", crime_rows,
        ["node_id","crime_no","case_no","crime_type","district_id","district_name",
         "registered_date","status","amount_involved","vector_id"])

    # nodes_person.csv
    person_node_ids: set = set()
    person_rows = []
    person_map = {p.person_id: p for p in corpus.persons}
    for fir in corpus.firs:
        for acc_pid in fir.accused_person_ids:
            if acc_pid in person_node_ids:
                continue
            person_node_ids.add(acc_pid)
            acc_id = reg.get_accused_master_id(acc_pid)
            p = person_map.get(acc_pid)
            if p and acc_id:
                person_rows.append({
                    "node_id": f"ACC:{acc_id}", "full_name": p.full_name,
                    "role": p.role, "age": p.age, "gender": p.gender,
                    "occupation": p.occupation, "district": p.district,
                })
        comp_pid = fir.complainant_person_id
        if comp_pid and comp_pid not in person_node_ids:
            person_node_ids.add(comp_pid)
            comp_id = reg.get_complainant_id(comp_pid)
            p = person_map.get(comp_pid)
            if p and comp_id:
                person_rows.append({
                    "node_id": f"COMP:{comp_id}", "full_name": p.full_name,
                    "role": p.role, "age": p.age, "gender": p.gender,
                    "occupation": p.occupation, "district": p.district,
                })
    _write_csv(graph / "nodes_person.csv", person_rows,
        ["node_id","full_name","role","age","gender","occupation","district"])

    # Object nodes — keyed by natural identifier value (de-duplicated)
    _write_csv(graph / "nodes_account.csv",
        [{"node_id": a.account_no, "bank": a.bank, "ifsc": a.ifsc,
          "branch_district": a.branch_district,
          "is_flagged_mule": int(a.is_flagged_mule), "kyc_name": a.kyc_name}
         for a in corpus.accounts],
        ["node_id","bank","ifsc","branch_district","is_flagged_mule","kyc_name"])
    _write_csv(graph / "nodes_phone.csv",
        [{"node_id": p.number, "number": p.number} for p in corpus.phones],
        ["node_id","number"])
    _write_csv(graph / "nodes_device.csv",
        [{"node_id": d.imei, "imei": d.imei} for d in corpus.devices],
        ["node_id","imei"])
    _write_csv(graph / "nodes_upi.csv",
        [{"node_id": u.vpa, "vpa": u.vpa} for u in corpus.upis],
        ["node_id","vpa"])
    _write_csv(graph / "nodes_ip.csv",
        [{"node_id": ip.ip_address, "ip_address": ip.ip_address,
          "geo_city": ip.geolocation.get("city","")}
         for ip in corpus.ips],
        ["node_id","ip_address","geo_city"])
    _write_csv(graph / "nodes_wallet.csv",
        [{"node_id": w.address, "address": w.address, "chain": w.chain}
         for w in corpus.wallets],
        ["node_id","address","chain"])

    # Legal nodes
    _write_csv(graph / "nodes_section.csv",
        [{"node_id": s.section_id, "act": s.act, "section_number": s.section_number,
          "title": s.title}
         for s in LEGAL_SECTIONS],
        ["node_id","act","section_number","title"])
    _write_csv(graph / "nodes_legal_element.csv",
        [{"node_id": e.element_id, "section_id": e.section_id, "name": e.name}
         for e in LEGAL_ELEMENTS],
        ["node_id","section_id","name"])
    _write_csv(graph / "nodes_evidence_type.csv",
        [{"node_id": e.evidence_type_id, "name": e.name,
          "requires_63": int(e.requires_63_certificate)}
         for e in EVIDENCE_TYPES],
        ["node_id","name","requires_63"])
    _write_csv(graph / "nodes_precedent.csv",
        [{"node_id": p.precedent_id, "case_name": p.case_name,
          "citation": p.citation, "year": p.year,
          "outcome": p.outcome, "holding_summary": p.holding_summary}
         for p in PRECEDENTS],
        ["node_id","case_name","citation","year","outcome","holding_summary"])
    _write_csv(graph / "nodes_ipc_section.csv",
        [{"node_id": s.ipc_section_id, "section_number": s.section_number,
          "title": s.title}
         for s in IPC_SECTIONS],
        ["node_id","section_number","title"])

    # Relationship edges — all carry source_caseid/observed_date/confidence
    uses_rows = []
    for e in corpus.uses_edges:
        src_cm = reg.resolve_source_fir_id(e.get("source_fir_id","")) or e.get("source_fir_id","")
        uses_rows.append({
            ":START_ID":     e["from_person_id"],
            ":END_ID":       e["to_object_id"],
            ":TYPE":         "USES",
            "source_caseid": src_cm,
            "observed_date": e.get("observed_date",""),
            "confidence":    e.get("confidence",1.0),
            "role":          e.get("role",""),
        })
    _write_csv(graph / "rels_uses.csv", uses_rows,
        [":START_ID",":END_ID",":TYPE","source_caseid","observed_date","confidence","role"])

    accused_in, comp_in, occurred_in = [], [], []
    for fir in corpus.firs:
        cm_id = reg.get_case_master_id(fir.fir_id)
        if cm_id is None:
            continue
        for acc_pid in fir.accused_person_ids:
            acc_id = reg.get_accused_master_id(acc_pid)
            if acc_id:
                accused_in.append({
                    ":START_ID": f"ACC:{acc_id}", ":END_ID": cm_id, ":TYPE": "ACCUSED_IN",
                    "source_caseid": cm_id, "observed_date": fir.date_registered,
                    "confidence": 1.0,
                })
        comp_id = reg.get_complainant_id(fir.complainant_person_id)
        if comp_id:
            comp_in.append({
                ":START_ID": f"COMP:{comp_id}", ":END_ID": cm_id, ":TYPE": "COMPLAINANT_IN",
                "source_caseid": cm_id, "observed_date": fir.date_registered,
                "confidence": 1.0,
            })
        occurred_in.append({
            ":START_ID": cm_id, ":END_ID": fir.district or "Unknown",
            ":TYPE": "OCCURRED_IN",
        })
    _write_csv(graph / "rels_accused_in.csv", accused_in,
        [":START_ID",":END_ID",":TYPE","source_caseid","observed_date","confidence"])
    _write_csv(graph / "rels_complainant_in.csv", comp_in,
        [":START_ID",":END_ID",":TYPE","source_caseid","observed_date","confidence"])
    _write_csv(graph / "rels_occurred_in.csv", occurred_in,
        [":START_ID",":END_ID",":TYPE"])

    transferred = []
    for t in corpus.transactions:
        src_cm = reg.resolve_source_fir_id(t.source_fir_id) or ""
        transferred.append({
            ":START_ID":     t.from_account, ":END_ID": t.to_account,
            ":TYPE":         "TRANSFERRED_TO",
            "amount":        t.amount, "timestamp": t.timestamp,
            "channel":       t.channel, "hop_role": t.hop_role,
            "source_caseid": src_cm,
            "observed_date": t.timestamp[:10] if t.timestamp else "",
            "confidence":    1.0,
        })
    _write_csv(graph / "rels_transferred_to.csv", transferred,
        [":START_ID",":END_ID",":TYPE","amount","timestamp","channel",
         "hop_role","source_caseid","observed_date","confidence"])

    mentions = []
    for fir in corpus.firs:
        cm_id = reg.get_case_master_id(fir.fir_id)
        if cm_id is None:
            continue
        for obj_type, obj_ids in fir.identifiers_mentioned.items():
            for oid in obj_ids:
                mentions.append({
                    ":START_ID": cm_id, ":END_ID": oid, ":TYPE": "MENTIONS",
                    "object_type": obj_type,
                    "source_caseid": cm_id, "observed_date": fir.date_registered,
                    "confidence": 1.0,
                })
    _write_csv(graph / "rels_mentions.csv", mentions,
        [":START_ID",":END_ID",":TYPE","object_type","source_caseid","observed_date","confidence"])

    _write_csv(graph / "rels_replaces.csv", REPLACES_EDGES, [":START_ID",":END_ID",":TYPE"])
    _write_csv(graph / "rels_requires_element.csv", REQUIRES_EDGES, [":START_ID",":END_ID",":TYPE"])
    _write_csv(graph / "rels_satisfied_by.csv", SATISFIED_BY_EDGES,
        [":START_ID",":END_ID",":TYPE","fir_id","element_id"])
    _write_csv(graph / "rels_supports.csv", SUPPORTS_EDGES, [":START_ID",":END_ID",":TYPE"])
    _write_csv(graph / "rels_failed_on.csv", FAILED_ON_EDGES, [":START_ID",":END_ID",":TYPE","fir_id"])
    _write_csv(graph / "rels_interprets.csv", INTERPRETS_EDGES, [":START_ID",":END_ID",":TYPE"])
    _write_csv(graph / "rels_has_evidence.csv",
        get_has_evidence_edges(corpus.firs, reg),
        [":START_ID",":END_ID",":TYPE","source_caseid"])
    _write_csv(graph / "rels_charged_under.csv",
        get_charged_under_edges(corpus.firs, fir_projections, reg),
        [":START_ID",":END_ID",":TYPE","source_caseid"])

    _write_import_cypher(graph)

# ---------------------------------------------------------------------------
# Cypher import script
# ---------------------------------------------------------------------------

def _write_import_cypher(graph: Path) -> None:
    cypher = """// Neo4j import script - KSP Crime Intelligence Platform
// Object nodes keyed by natural identifier (MERGE semantics to preserve cross-case links)

LOAD CSV WITH HEADERS FROM 'file:///nodes_crime.csv' AS row
MERGE (c:Crime {node_id: toInteger(row.node_id)})
SET c.crime_no=row.crime_no, c.case_no=row.case_no, c.crime_type=row.crime_type,
    c.district_id=toInteger(row.district_id), c.district_name=row.district_name,
    c.registered_date=row.registered_date, c.amount_involved=toInteger(row.amount_involved);

LOAD CSV WITH HEADERS FROM 'file:///nodes_person.csv' AS row
MERGE (p:Person {node_id: row.node_id})
SET p.full_name=row.full_name, p.role=row.role, p.age=toInteger(row.age),
    p.gender=row.gender, p.occupation=row.occupation, p.district=row.district;

LOAD CSV WITH HEADERS FROM 'file:///nodes_account.csv' AS row
MERGE (a:Account {node_id: row.node_id})
SET a.bank=row.bank, a.ifsc=row.ifsc, a.is_flagged_mule=toBoolean(row.is_flagged_mule);

LOAD CSV WITH HEADERS FROM 'file:///nodes_phone.csv' AS row
MERGE (p:Phone {node_id: row.node_id}) SET p.number=row.number;

LOAD CSV WITH HEADERS FROM 'file:///nodes_device.csv' AS row
MERGE (d:Device {node_id: row.node_id}) SET d.imei=row.imei;

LOAD CSV WITH HEADERS FROM 'file:///nodes_upi.csv' AS row
MERGE (u:UPI {node_id: row.node_id}) SET u.vpa=row.vpa;

LOAD CSV WITH HEADERS FROM 'file:///nodes_ip.csv' AS row
MERGE (i:IP {node_id: row.node_id}) SET i.ip_address=row.ip_address, i.geo_city=row.geo_city;

LOAD CSV WITH HEADERS FROM 'file:///nodes_wallet.csv' AS row
MERGE (w:Wallet {node_id: row.node_id}) SET w.address=row.address, w.chain=row.chain;

// Indexes
CREATE INDEX crime_idx FOR (c:Crime) ON (c.node_id);
CREATE INDEX person_idx FOR (p:Person) ON (p.node_id);
CREATE INDEX account_idx FOR (a:Account) ON (a.node_id);
CREATE INDEX device_idx FOR (d:Device) ON (d.node_id);
CREATE INDEX upi_idx FOR (u:UPI) ON (u.node_id);

// See rels_*.csv for relationships (bulk import via neo4j-admin).
"""
    (graph / "import.cypher").write_text(cypher, encoding="utf-8")

# ---------------------------------------------------------------------------
# Vector JSONL writer  (reads FULL docs from docs/ folder; falls back to narrative_map)
# ---------------------------------------------------------------------------

def write_vector_jsonl(base: Path, corpus: Corpus,
                       fir_projections: Dict[str, Dict],
                       narrative_map: Dict[str, str],
                       docs_root: Optional[Path] = None) -> None:
    """
    Write narratives.jsonl with FULL document text.
    node_id = INT CaseMasterID for FIR docs.
    node_id = "IR:<ReportID>" for IR docs.
    Reads from docs/<CrimeNo>/fir.txt if available; falls back to narrative_map.
    Metadata: CrimeNo, district, crime_type, date, lang, doc_type.
    """
    import logging as _log
    vec_dir = base / "vector"
    _mkdir(vec_dir)
    records = []
    _docs_root = docs_root or (base / "docs")

    # crime_type/district per case, so IR vectors carry the same metadata as their FIR
    # (needed for MO filtering; IR records otherwise had empty crime_type/district).
    fir_meta_by_cmid: Dict[int, Dict[str, str]] = {}

    for fir in corpus.firs:
        cm_id = reg.get_case_master_id(fir.fir_id)
        if cm_id is None:
            continue
        proj = fir_projections.get(fir.fir_id, {})
        crime_no = proj.get("crime_no","")
        unit_id  = proj.get("unit_id", 1001)
        unit_obj = km.UNIT_MAP.get(unit_id)
        dist_obj = km.DISTRICT_BY_ID.get(unit_obj.district_id if unit_obj else 0)
        district_name = dist_obj.district_name if dist_obj else "Unknown"
        fir_meta_by_cmid[cm_id] = {"crime_type": fir.crime_type, "district": district_name}
        # Embed the MO NARRATIVE PROSE, not the full structured FIR document. The KSP
        # header/complainant/sections boilerplate is near-identical across all crime
        # types, so embedding the whole doc clusters by format and buries the MO signal
        # (digital-arrest cases ranked #38/#50 behind unrelated task-scams). The prose is
        # what carries "same script" similarity. Fall back to the doc only if prose is missing.
        text = narrative_map.get(fir.fir_id) or ""
        if not text.strip():
            fir_doc_path = _docs_root / crime_no / "fir.txt"
            text = fir_doc_path.read_text(encoding="utf-8") if fir_doc_path.exists() else ""
        # future-consistency: key names match data_ingestion/config.VECTOR_METADATA_FIELDS.
        # latitude/longitude/pincode/district_id removed; ingest-time SQL join is authoritative.
        records.append({
            "node_id":  cm_id,
            "text":     text,
            "doc_type": "fir",
            "metadata": {
                "CrimeNo":             crime_no,
                "district":            district_name,
                "crime_type":          fir.crime_type,
                "CrimeRegisteredDate": fir.date_registered,
                "date_of_offence":     fir.date_of_offence,
                "amount_involved":     fir.amount_involved,
                "lang":                "en",
                "doc_type":            "fir",
                "fir_logical_id":      fir.fir_id,
            }
        })

    for ir in corpus.investigation_reports:
        cm_id = reg.resolve_source_fir_id(ir.fir_id) or reg.get_case_master_id(ir.fir_id)
        if cm_id is None:
            continue
        rid = reg.get_report_id(ir.report_id) or reg.report_id(ir.report_id)
        ir_proj = fir_projections.get(ir.fir_id, {})
        crime_no = ir_proj.get("crime_no","")
        # Embed IR prose, not the full doc (same reasoning as the FIR branch above).
        text = narrative_map.get(ir.report_id) or ir.money_trail_notes or ""
        if not text.strip():
            ir_doc_path = _docs_root / crime_no / "investigation_report.txt"
            text = ir_doc_path.read_text(encoding="utf-8") if ir_doc_path.exists() else ""
        fmeta = fir_meta_by_cmid.get(cm_id, {})
        records.append({
            "node_id":  f"IR:{rid}",
            "text":     text,
            "doc_type": "ir",
            "metadata": {
                "CrimeNo":        crime_no,
                "report_id":      ir.report_id,
                "case_master_id": cm_id,
                "report_date":    ir.report_date,
                # Inherit the case's crime_type/district so IR vectors filter like FIRs.
                "crime_type":     fmeta.get("crime_type", ""),
                "district":       fmeta.get("district", ""),
                "lang":           "en",
                "doc_type":       "ir",
                "is_live":        ir.is_live,
            }
        })

    with open(vec_dir / "narratives.jsonl", "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _log.getLogger("export").info(
        f"Vector JSONL: {len(records)} records -> {vec_dir / 'narratives.jsonl'}")
# ---------------------------------------------------------------------------
# Main export entry point
# ---------------------------------------------------------------------------

def run_export(corpus: Corpus, narrative_map: Dict[str, str],
               output_dir: str = None, staging_dir: str = None,
               rng_seed: int = None) -> str:
    import logging
    log = logging.getLogger("export")
    output_dir = output_dir or config.OUTPUT_DIR
    staging_dir = staging_dir or config.OUTPUT_STAGING_DIR
    rng = random.Random(rng_seed or config.RANDOM_SEED)

    staging = Path(staging_dir) / "historical"
    _mkdir(staging)

    log.info("Resetting counters and projecting FIRs...")
    reset_asa_counter()
    global _arrest_counter
    _arrest_counter = 0
    project_fir._cs_counter = 0

    person_map: Dict[str, Person] = {p.person_id: p for p in corpus.persons}
    fir_projections: Dict[str, Dict] = {}
    for fir in corpus.firs:
        year = int(fir.date_registered[:4]) if fir.date_registered else 2026
        proj = project_fir(fir, person_map, rng, year=year)
        proj["case_master"]["BriefFacts"] = narrative_map.get(fir.fir_id,"")
        fir_projections[fir.fir_id] = proj
    log.info(f"Projected {len(fir_projections)} FIRs")

    write_masters(staging)
    write_ksp_core_csvs(staging, fir_projections)
    write_extension_csvs(staging, corpus, fir_projections)
    write_graph(staging, corpus, fir_projections, narrative_map)
    write_vector_jsonl(staging, corpus, fir_projections, narrative_map)

    out = Path(output_dir) / "historical"
    if out.exists():
        bak = Path(config.OUTPUT_BACKUP_DIR) / "historical"
        if bak.exists():
            shutil.rmtree(bak)
        shutil.copytree(out, bak)
        shutil.rmtree(out)
    shutil.move(str(staging), str(out))

    success = Path(output_dir) / "_SUCCESS"
    success.write_text("OK")
    log.info(f"Export complete: {out}")
    return str(success)

def build_projections(corpus: Corpus, rng_seed: int = None) -> Dict[str, Dict]:
    rng = random.Random(rng_seed or config.RANDOM_SEED)
    person_map: Dict[str, Person] = {p.person_id: p for p in corpus.persons}
    global _arrest_counter
    _arrest_counter = 0
    project_fir._cs_counter = 0
    reset_asa_counter()
    projections = {}
    for fir in corpus.firs:
        year = int(fir.date_registered[:4]) if fir.date_registered else 2026
        proj = project_fir(fir, person_map, rng, year=year)
        projections[fir.fir_id] = proj
    return projections
