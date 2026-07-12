"""
models.py — Dataclasses for all entities in the KSP Crime Intelligence Platform dataset.
KSP-core dataclasses are ER-exact (Police_FIR_ER_Diagram.pdf).
Extension dataclasses are additive; they never alter ER columns.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Sub-event (for FIR case-timeline reconstruction)
# ---------------------------------------------------------------------------
@dataclass
class SubEvent:
    label: str          # e.g. "call received", "first transfer", "complaint filed"
    timestamp: str      # ISO-8601 datetime string with minute precision


# ---------------------------------------------------------------------------
# FIR / Crime
# ---------------------------------------------------------------------------
@dataclass
class FIR:
    fir_id: str                         # stable UUID used across SQL/graph/vector
    fir_number: str                     # e.g. "CR-045/2026"
    crime_type: str                     # task_scam | digital_arrest | …
    date_registered: str                # ISO date
    date_of_offence: str                # ISO date
    district: str
    pincode: str                        # 6-digit Karnataka pincode
    lat: float
    long: float
    police_station: str
    complainant_person_id: str
    accused_person_ids: list[str] = field(default_factory=list)
    amount_involved: int = 0            # in Indian Rupees
    bns_sections: list[str] = field(default_factory=list)
    it_act_sections: list[str] = field(default_factory=list)
    identifiers_mentioned: dict[str, list[str]] = field(default_factory=lambda: {
        "phones": [], "accounts": [], "upis": [], "imeis": [], "ips": [], "wallets": []
    })
    status: str = "Under Investigation"
    io_officer: str = ""
    narrative_vector_id: str = ""       # pointer to vector store record
    sub_events: list[SubEvent] = field(default_factory=list)
    narrative_tier: str = ""            # "A" | "B" | "C" | "decoy" — used by narrative generator
    is_synthetic: bool = True


# ---------------------------------------------------------------------------
# Investigation Report
# ---------------------------------------------------------------------------
@dataclass
class InvestigationReport:
    report_id: str
    fir_id: str
    report_date: str
    io_officer: str
    findings_vector_id: str = ""
    newly_linked_identifiers: dict[str, list[str]] = field(default_factory=lambda: {
        "phones": [], "accounts": [], "upis": [], "imeis": [], "ips": [], "wallets": []
    })
    linked_fir_ids: list[str] = field(default_factory=list)
    seized_items: list[str] = field(default_factory=list)
    arrests: list[str] = field(default_factory=list)
    money_trail_notes: str = ""
    suspected_roles: list[dict[str, str]] = field(default_factory=list)  # [{person_id, role}]
    is_live: bool = False               # True = held-back live-demo doc


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------
@dataclass
class Person:
    person_id: str
    full_name: str
    aliases: list[str] = field(default_factory=list)
    age: int = 0
    gender: str = "Male"
    address: str = ""
    district: str = ""
    education: str = ""
    occupation: str = ""
    employment_status: str = ""
    role: str = "victim"      # victim | recruiter | caller | mule | mule_handler | controller
    first_seen_date: str = ""
    kyc_ids: dict[str, str] = field(default_factory=lambda: {"pan": "", "aadhaar_synth": ""})
    is_synthetic: bool = True
    # NOTE: linked_case_count is deliberately NOT exported to prevent misleading
    # per-alias pre-resolution counts. True cross-alias count is in planted_links.md only.


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------
@dataclass
class Account:
    account_no: str
    bank: str
    ifsc: str                  # format: 4 letters + 0 + 6 alphanumeric
    branch_district: str
    account_type: str = "Savings"
    open_date: str = ""
    kyc_name: str = ""         # may be blank for mule accounts awaiting reveal
    is_flagged_mule: bool = False
    activity_history: list[dict[str, Any]] = field(default_factory=list)
    # each entry: {timestamp, direction: "in"|"out", amount}


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------
@dataclass
class Transaction:
    txn_id: str
    from_account: str          # account_no or wallet address
    to_account: str            # account_no or wallet address
    amount: int                # in Rupees
    timestamp: str             # ISO datetime with minute precision
    channel: str               # UPI | IMPS | NEFT | cash | crypto
    linked_fir_id: str = ""
    hop_role: str = "mule"     # origin | collection | aggregation | mule | cash_out
    source_fir_id: str = ""    # provenance


# ---------------------------------------------------------------------------
# Object types
# ---------------------------------------------------------------------------
@dataclass
class Phone:
    phone_id: str
    number: str


@dataclass
class Device:
    device_id: str
    imei: str


@dataclass
class UPI:
    upi_id: str
    vpa: str                   # e.g. "user@bankname"


@dataclass
class IP:
    ip_id: str
    ip_address: str
    geolocation: dict[str, Any] = field(default_factory=lambda: {"lat": 0.0, "long": 0.0, "city": ""})


@dataclass
class Wallet:
    wallet_id: str
    address: str
    chain: str = "USDT"


# ---------------------------------------------------------------------------
# Legal layer entities  (REAL data — not synthetic)
# ---------------------------------------------------------------------------
@dataclass
class LegalSection:
    section_id: str            # e.g. "IT_66C", "BNS_318"
    act: str                   # IT Act | BNS | PMLA | BSA | BNSS
    section_number: str        # e.g. "66C", "318"
    title: str
    description: str
    replaces_ipc: Optional[str] = None    # IPC section this BNS section replaces


@dataclass
class LegalElement:
    element_id: str
    section_id: str
    name: str
    description: str


@dataclass
class EvidenceType:
    evidence_type_id: str
    name: str
    description: str
    requires_63_certificate: bool = False


@dataclass
class Precedent:
    precedent_id: str
    case_name: str
    citation: str
    year: int
    court: str
    outcome: str               # "conviction" | "acquittal"
    element_turned_on: str     # element_id this case turned on
    section_id: str
    holding_summary: str       # short displayable text
    is_overruled: bool = False


@dataclass
class Evidence:
    evidence_id: str
    fir_id: str
    evidence_type_id: str
    description: str
    admissible: bool = True
    has_63_certificate: bool = True    # False = planted amber gap


@dataclass
class IPCSection:
    ipc_section_id: str        # e.g. "IPC_420"
    section_number: str        # e.g. "420"
    title: str


# ---------------------------------------------------------------------------
# Reference entities
# ---------------------------------------------------------------------------
@dataclass
class District:
    name: str
    lat: float
    long: float
    pincodes: list[str] = field(default_factory=list)
    district_id: int = 0    # 4-digit KSP DistrictID (e.g. 2901); 0 = not yet assigned


@dataclass
class PoliceStation:
    station_id: str
    name: str
    district: str
    station_type: str = "cyber"   # cyber | CEN | general
    unit_id: int = 0              # 4-digit KSP UnitID; 0 = not yet assigned
    district_id: int = 0          # mirrors Unit.DistrictID for fast lookup


@dataclass
class Bank:
    name: str
    ifsc_prefix: str   # 4-letter bank code


@dataclass
class CrimeType:
    code: str
    label: str


# ---------------------------------------------------------------------------
# Aggregate corpus container (passed between pipeline stages)
# ---------------------------------------------------------------------------
@dataclass
class Corpus:
    firs: list[FIR] = field(default_factory=list)
    investigation_reports: list[InvestigationReport] = field(default_factory=list)
    persons: list[Person] = field(default_factory=list)
    accounts: list[Account] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    phones: list[Phone] = field(default_factory=list)
    devices: list[Device] = field(default_factory=list)
    upis: list[UPI] = field(default_factory=list)
    ips: list[IP] = field(default_factory=list)
    wallets: list[Wallet] = field(default_factory=list)
    # USES edges: [{from_person_id, to_object_id, object_type, source_fir_id, observed_date, confidence}]
    uses_edges: list[dict[str, Any]] = field(default_factory=list)
    # Live-demo documents (held back — not pre-loaded)
    live_firs: list[FIR] = field(default_factory=list)
    live_irs: list[InvestigationReport] = field(default_factory=list)


# =============================================================================
# KSP-CORE DATACLASSES
# These are the projection targets for export.py.
# The internal generator model (FIR, Person above) is kept unchanged.
# NOTE: pincode is NOT a CaseMaster column — it moves to CaseGeo (extension).
#       latitude/longitude DO stay on CaseMaster.
# =============================================================================

# ---------------------------------------------------------------------------
# CaseMaster (KSP SQL core)
# ---------------------------------------------------------------------------
@dataclass
class CaseMaster:
    case_master_id: int             # INT PK assigned by id_registry
    crime_no: str                   # 18-digit formatted CrimeNo
    case_no: str                    # last 9 digits of CrimeNo
    crime_registered_date: str      # ISO datetime
    police_person_id: int           # FK -> Employee.employee_id (IO officer)
    police_station_id: int          # FK -> Unit.unit_id
    case_category_id: int           # FK -> CaseCategory (1=FIR)
    gravity_offence_id: int         # FK -> GravityOffence
    crime_major_head_id: int        # FK -> CrimeHead
    crime_minor_head_id: int        # FK -> CrimeSubHead
    case_status_id: int             # FK -> CaseStatusMaster
    court_id: int                   # FK -> Court
    incident_from_date: str         # ISO datetime
    incident_to_date: str           # ISO datetime
    info_received_ps_date: str      # ISO datetime
    latitude: float
    longitude: float
    brief_facts: str                # Nvarchar(Max) — narrative text (English or Kannada)
    fir_logical_id: str = ""        # internal reference — not exported to CSV
    is_live: bool = False           # True = held-back live-demo doc


# ---------------------------------------------------------------------------
# ComplainantDetails (KSP SQL core)
# ---------------------------------------------------------------------------
@dataclass
class KSPComplainantDetails:
    # ER-exact columns: ComplainantID, CaseMasterID, ComplainantName, AgeYear, GenderID,
    #                   OccupationID, CasteID, ReligionID
    complainant_id: int             # INT PK
    case_master_id: int             # FK -> CaseMaster
    complainant_name: str
    age_year: int
    gender_id: str                  # "M" | "F" | "T"
    occupation_id: int              # FK -> OccupationMaster
    caste_id: int                   # FK -> CasteMaster (conformance only)
    religion_id: int                # FK -> ReligionMaster (conformance only)
    address: str = ""
    mobile: str = ""
    person_logical_id: str = ""     # internal — not exported


# ---------------------------------------------------------------------------
# Victim (KSP SQL core)
# ---------------------------------------------------------------------------
@dataclass
class KSPVictim:
    # ER-exact columns: VictimMasterID, CaseMasterID, VictimName, AgeYear, GenderID, VictimPolice
    victim_master_id: int           # INT PK
    case_master_id: int             # FK -> CaseMaster
    victim_name: str
    age_year: int
    gender_id: str                  # "M" | "F" | "T"
    victim_police: int              # FK -> Employee (IO who recorded victim); ER column VictimPolice
    # Extension fields (additive — not ER columns; moved to EXT_VictimDetail)
    occupation_id: int = 39
    caste_id: int = 5
    religion_id: int = 5
    address: str = ""
    mobile: str = ""
    loss_amount: int = 0
    person_logical_id: str = ""


# ---------------------------------------------------------------------------
# Accused (KSP SQL core)
# ---------------------------------------------------------------------------
@dataclass
class KSPAccused:
    # ER-exact columns: AccusedMasterID, CaseMasterID, AccusedName, AgeYear, GenderID, PersonID
    accused_master_id: int          # INT PK
    case_master_id: int             # FK -> CaseMaster
    person_id: str                  # VARCHAR e.g. "A1", "A2" (ER column PersonID)
    accused_name: str
    age_year: int
    gender_id: str                  # "M" | "F" | "T"
    # Extension fields (additive — not ER columns; moved to EXT_AccusedDetail)
    occupation_id: int = 39
    caste_id: int = 5
    religion_id: int = 5
    address: str = ""
    is_arrested: bool = False
    # IMPORTANT: live accused stay un-merged — own AccusedMasterID,
    # shares identifiers (IMEI/UPI) with historical aliases via extension USES edges.
    # No RESOLVED_AS or LINKED_TO edges are ever pre-baked.
    person_logical_id: str = ""     # internal — not exported


# ---------------------------------------------------------------------------
# ArrestSurrender (KSP SQL core)
# ---------------------------------------------------------------------------
@dataclass
class KSPArrestSurrender:
    # ER-exact columns:
    # ArrestSurrenderID, CaseMasterID, ArrestSurrenderTypeID, ArrestSurrenderDate,
    # ArrestSurrenderStateId, ArrestSurrenderDistrictId, PoliceStationID, IOID,
    # CourtID, AccusedMasterID, IsAccused, IsComplainantAccused
    arrest_surrender_id: int        # INT PK
    case_master_id: int             # FK -> CaseMaster
    arrest_surrender_type_id: int   # 1=Arrest, 2=Surrender
    arrest_surrender_date: str      # ISO date
    arrest_surrender_state_id: int  # FK -> State.StateID (29 for Karnataka)
    arrest_surrender_district_id: int  # FK -> District.DistrictID
    police_station_id: int          # FK -> Unit.UnitID
    ioid: int                       # FK -> Employee (IO who effected arrest)
    court_id: int                   # FK -> Court
    accused_master_id: int          # FK -> Accused.AccusedMasterID
    is_accused: int = 1             # 1=Yes
    is_complainant_accused: int = 0 # 1=Yes (rare)


# ---------------------------------------------------------------------------
# ActSectionAssociation (KSP SQL core)
# ---------------------------------------------------------------------------
@dataclass
class KSPActSectionAssociation:
    # ER-exact columns:
    # CaseMasterID, ActCode, SectionCode, ActOrderID, SectionOrderID
    # (composite key: CaseMasterID + ActCode + SectionCode; no surrogate ASAID per ER)
    case_master_id: int             # FK -> CaseMaster
    act_code: str                   # VARCHAR FK -> Act.ActCode
    section_code: str               # VARCHAR FK -> Section.SectionCode
    act_order_id: int = 1           # ordering of this Act within the case
    section_order_id: int = 1       # ordering of this Section within the Act for this case


# ---------------------------------------------------------------------------
# ChargesheetDetails (KSP SQL core)
# ---------------------------------------------------------------------------
@dataclass
class KSPChargesheetDetails:
    cs_id: int                      # INT PK
    case_master_id: int             # FK -> CaseMaster
    cs_date: str                    # ISO date (may be empty for Undetected)
    cstype: str                     # "C"=Undetected ~85%, "A"=Chargesheet ~10%, "B"=False ~5%
    police_person_id: int           # FK -> Employee (IO who filed / closed)


# ---------------------------------------------------------------------------
# CaseGeo (extension table — pincode lives here, NOT on CaseMaster)
# ---------------------------------------------------------------------------
@dataclass
class CaseGeo:
    geo_id: int                     # INT PK (ext_obj_id from registry)
    case_master_id: int             # FK -> CaseMaster
    pincode: str                    # 6-digit Karnataka pincode
    incident_district: str          # derived from Unit.district_id for display
