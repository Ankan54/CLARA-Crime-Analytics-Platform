"""
ksp_master.py - Seed all KSP master/lookup tables with INT PKs.
ER-exact: every field name, type, and key matches Police_FIR_ER_Diagram.pdf.
Extensions (crime_type_code on CrimeSubHead) are additive internal helpers only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
STATE_ID_KARNATAKA = 29
STATE_NAME_KARNATAKA = "Karnataka"

# ---------------------------------------------------------------------------
# UnitType master  (ER: UnitTypeID, UnitTypeName, CityDistState, Hierarchy, Active)
# ---------------------------------------------------------------------------
@dataclass
class KSPUnitType:
    unit_type_id: int
    unit_type_name: str
    city_dist_state: str = "District"
    hierarchy: int = 3
    active: int = 1

UNIT_TYPES: List[KSPUnitType] = [
    KSPUnitType(1, "Police Station",       "District", 3, 1),
    KSPUnitType(2, "CEN",                  "District", 3, 1),
    KSPUnitType(3, "Cyber Crime Station",  "District", 3, 1),
    KSPUnitType(4, "District Headquarters","District", 2, 1),
]
UNIT_TYPE_MAP: Dict[str, int] = {ut.unit_type_name: ut.unit_type_id for ut in UNIT_TYPES}

# ---------------------------------------------------------------------------
# Rank master  (ER: RankID, RankName, Hierarchy, Active)
# ---------------------------------------------------------------------------
@dataclass
class KSPRank:
    rank_id: int
    rank_name: str
    hierarchy: int = 5
    active: int = 1

RANKS: List[KSPRank] = [
    KSPRank(1,  "Director General of Police", 1, 1),
    KSPRank(2,  "Inspector General",          2, 1),
    KSPRank(3,  "Deputy Inspector General",   3, 1),
    KSPRank(4,  "Superintendent of Police",   4, 1),
    KSPRank(5,  "Additional Superintendent",  5, 1),
    KSPRank(6,  "Deputy Superintendent",      6, 1),
    KSPRank(7,  "Inspector",                  7, 1),
    KSPRank(8,  "Sub-Inspector",              8, 1),
    KSPRank(9,  "Assistant Sub-Inspector",    9, 1),
    KSPRank(10, "Head Constable",             10, 1),
    KSPRank(11, "Police Constable",           11, 1),
]
RANK_MAP: Dict[str, int] = {r.rank_name: r.rank_id for r in RANKS}

# ---------------------------------------------------------------------------
# Designation master  (ER: DesignationID, DesignationName, Active, SortOrder)
# ---------------------------------------------------------------------------
@dataclass
class KSPDesignation:
    designation_id: int
    designation_name: str
    active: int = 1
    sort_order: int = 0

DESIGNATIONS: List[KSPDesignation] = [
    KSPDesignation(1, "Police Inspector",       1, 1),
    KSPDesignation(2, "Sub-Inspector of Police",1, 2),
    KSPDesignation(3, "Assistant Sub-Inspector",1, 3),
    KSPDesignation(4, "Head Constable",         1, 4),
    KSPDesignation(5, "Police Constable",        1, 5),
    KSPDesignation(6, "Station House Officer",  1, 6),
    KSPDesignation(7, "IO (Cyber)",             1, 7),
    KSPDesignation(8, "IO (CEN)",               1, 8),
]
DESIGNATION_MAP: Dict[str, int] = {d.designation_name: d.designation_id for d in DESIGNATIONS}

# ---------------------------------------------------------------------------
# District master  (ER: DistrictID, DistrictName, StateID, Active)
# ---------------------------------------------------------------------------
@dataclass
class KSPDistrict:
    district_id: int
    district_name: str
    state_id: int = STATE_ID_KARNATAKA
    active: int = 1

DISTRICTS: List[KSPDistrict] = [
    KSPDistrict(2901, "Bengaluru Urban"),
    KSPDistrict(2902, "Bengaluru Rural"),
    KSPDistrict(2903, "Mysuru"),
    KSPDistrict(2904, "Mangaluru"),
    KSPDistrict(2905, "Hubballi-Dharwad"),
    KSPDistrict(2906, "Belagavi"),
    KSPDistrict(2907, "Kalaburagi"),
    KSPDistrict(2908, "Ballari"),
    KSPDistrict(2909, "Shivamogga"),
    KSPDistrict(2910, "Davanagere"),
    KSPDistrict(2911, "Tumakuru"),
    KSPDistrict(2912, "Raichur"),
    KSPDistrict(2913, "Vijayapura"),
    KSPDistrict(2914, "Hassan"),
    KSPDistrict(2915, "Udupi"),
    KSPDistrict(2916, "Kodagu"),
    KSPDistrict(2917, "Chikkamagaluru"),
    KSPDistrict(2918, "Uttara Kannada"),
    KSPDistrict(2919, "Dharwad"),
    KSPDistrict(2920, "Gadag"),
    KSPDistrict(2921, "Koppal"),
    KSPDistrict(2922, "Yadgir"),
    KSPDistrict(2923, "Bidar"),
    KSPDistrict(2924, "Chamarajanagara"),
    KSPDistrict(2925, "Mandya"),
    KSPDistrict(2926, "Chikkaballapur"),
    KSPDistrict(2927, "Kolar"),
    KSPDistrict(2928, "Ramanagara"),
    KSPDistrict(2929, "Chitradurga"),
    KSPDistrict(2930, "Bagalkot"),
    KSPDistrict(2931, "Vijayanagara"),
]
DISTRICT_ID_MAP: Dict[str, int] = {d.district_name: d.district_id for d in DISTRICTS}
DISTRICT_BY_ID: Dict[int, KSPDistrict] = {d.district_id: d for d in DISTRICTS}

# ---------------------------------------------------------------------------
# Unit (Police Station) master
# ER: UnitID, UnitName, TypeID, ParentUnit, NationalityID, StateID, DistrictID, Active
# ---------------------------------------------------------------------------
@dataclass
class KSPUnit:
    unit_id: int
    unit_name: str
    district_id: int
    type_id: int          # FK -> UnitType.UnitTypeID  (ER column: TypeID)
    state_id: int = STATE_ID_KARNATAKA
    parent_unit: Optional[int] = None
    nationality_id: int = 1
    active: int = 1

UNITS: List[KSPUnit] = [
    # Bengaluru Urban (district_id=2901)
    KSPUnit(1001, "CEN Police Station - East Division",       2901, 2),
    KSPUnit(1002, "CEN Police Station - West Division",       2901, 2),
    KSPUnit(1003, "CEN Police Station - South Division",      2901, 2),
    KSPUnit(1004, "CEN Police Station - North Division",      2901, 2),
    KSPUnit(1005, "Whitefield Cyber Crime Police Station",    2901, 3),
    KSPUnit(1006, "Electronic City Cyber Crime Station",      2901, 3),
    KSPUnit(1007, "Koramangala Cyber Crime Station",          2901, 3),
    KSPUnit(1008, "HSR Layout Cyber Crime Station",           2901, 3),
    # Mysuru (2903)
    KSPUnit(1009, "Mysuru CEN Police Station",                2903, 2),
    KSPUnit(1010, "Chamundipuram Police Station",             2903, 1),
    KSPUnit(1011, "Devaraja Police Station",                  2903, 1),
    # Mangaluru (2904)
    KSPUnit(1012, "Mangaluru Cyber Crime Police Station",     2904, 3),
    KSPUnit(1013, "Bunder Police Station",                    2904, 1),
    # Hubballi-Dharwad (2905)
    KSPUnit(1014, "Hubballi CEN Police Station",              2905, 2),
    KSPUnit(1015, "Navanagar Police Station",                 2905, 1),
    # Belagavi (2906)
    KSPUnit(1016, "Belagavi CEN Police Station",              2906, 2),
    KSPUnit(1017, "Tilakwadi Police Station",                 2906, 1),
    # Dharwad (2919)
    KSPUnit(1018, "Dharwad Cyber Crime Police Station",       2919, 3),
    # Tumakuru (2911)
    KSPUnit(1019, "Tumakuru CEN Police Station",              2911, 2),
    KSPUnit(1020, "SS Puram Police Station",                  2911, 1),
    # Other districts
    KSPUnit(1021, "Kalaburagi CEN Police Station",            2907, 2),
    KSPUnit(1022, "Raichur Cyber Crime Station",              2912, 3),
    KSPUnit(1023, "Shivamogga CEN Police Station",            2909, 2),
    KSPUnit(1024, "Davanagere Cyber Crime Station",           2910, 3),
    KSPUnit(1025, "Hassan CEN Police Station",                2914, 2),
    KSPUnit(1026, "Udupi CEN Police Station",                 2915, 2),
    KSPUnit(1027, "Ballari CEN Police Station",               2908, 2),
    KSPUnit(1028, "Vijayapura CEN Police Station",            2913, 2),
    KSPUnit(1029, "Kolar CEN Police Station",                 2927, 2),
    KSPUnit(1030, "Chikkaballapur CEN Police Station",        2926, 2),
]

STATION_ID_TO_UNIT_ID: Dict[str, int] = {
    "PS_BLR_CEN_01":   1001, "PS_BLR_CEN_02":   1002,
    "PS_BLR_CEN_03":   1003, "PS_BLR_CEN_04":   1004,
    "PS_BLR_CYBER_01": 1005, "PS_BLR_CYBER_02": 1006,
    "PS_BLR_CYBER_03": 1007, "PS_BLR_CYBER_04": 1008,
    "PS_MYS_01": 1009, "PS_MYS_02": 1010, "PS_MYS_03": 1011,
    "PS_MNG_01": 1012, "PS_MNG_02": 1013,
    "PS_HUB_01": 1014, "PS_HUB_02": 1015,
    "PS_BLG_01": 1016, "PS_BLG_02": 1017,
    "PS_DWD_01": 1018,
    "PS_TUM_01": 1019, "PS_TUM_02": 1020,
    "PS_KLG_01": 1021, "PS_RCR_01": 1022,
    "PS_SHI_01": 1023, "PS_DAV_01": 1024,
    "PS_HAS_01": 1025, "PS_UDU_01": 1026,
    "PS_BAL_01": 1027, "PS_VJP_01": 1028,
    "PS_KOL_01": 1029, "PS_CHK_01": 1030,
}
UNIT_MAP: Dict[int, KSPUnit] = {u.unit_id: u for u in UNITS}

def get_district_id_for_station(station_id: str) -> int:
    uid = STATION_ID_TO_UNIT_ID.get(station_id)
    if uid is None:
        raise KeyError(f"Unknown station_id: {station_id}")
    return UNIT_MAP[uid].district_id

# ---------------------------------------------------------------------------
# Employee master
# ER: EmployeeID, DistrictID, UnitID, RankID, DesignationID, KGID, FirstName,
#     EmployeeDOB, GenderID, BloodGroupID, PhysicallyChallenged, AppointmentDate
# ---------------------------------------------------------------------------
@dataclass
class KSPEmployee:
    employee_id: int
    first_name: str
    unit_id: int
    rank_id: int
    designation_id: int
    district_id: int
    state_id: int = STATE_ID_KARNATAKA
    kgid: str = ""
    employee_dob: str = "1980-01-01"
    gender_id: int = 1
    blood_group_id: int = 1
    physically_challenged: int = 0
    appointment_date: str = "2005-01-01"

EMPLOYEES: List[KSPEmployee] = [
    KSPEmployee(5001, "Venkatesh Kumar",     1001, 7, 1, 2901, kgid="KG001001"),
    KSPEmployee(5002, "Priya Shankar",       1003, 7, 1, 2901, kgid="KG001002", gender_id=2),
    KSPEmployee(5003, "Manjunath Gowda",     1009, 7, 1, 2903, kgid="KG002001"),
    KSPEmployee(5004, "Savitha Nagaraj",     1012, 7, 1, 2904, kgid="KG003001", gender_id=2),
    KSPEmployee(5005, "Ravi Krishnamurthy",  1014, 7, 1, 2905, kgid="KG004001"),
    KSPEmployee(5006, "Anand Hegde",         1016, 7, 1, 2906, kgid="KG005001"),
    KSPEmployee(5007, "Deepa Kamath",        1018, 7, 1, 2919, kgid="KG006001", gender_id=2),
    KSPEmployee(5008, "Suresh Patil",        1019, 7, 1, 2911, kgid="KG007001"),
    KSPEmployee(5009, "Girish Rao",          1021, 7, 1, 2907, kgid="KG008001"),
    KSPEmployee(5010, "Kavitha Reddy",       1005, 7, 1, 2901, kgid="KG001003", gender_id=2),
    KSPEmployee(5011, "Basavaraj Gudadinni", 1023, 7, 1, 2909, kgid="KG009001"),
    KSPEmployee(5012, "Nirmala Shetty",      1025, 7, 1, 2914, kgid="KG010001", gender_id=2),
]
EMPLOYEE_MAP: Dict[str, int] = {e.first_name: e.employee_id for e in EMPLOYEES}
IO_NAME_TO_EMPLOYEE_ID: Dict[str, int] = {}
for _e in EMPLOYEES:
    IO_NAME_TO_EMPLOYEE_ID[f"PI {_e.first_name}"] = _e.employee_id
    IO_NAME_TO_EMPLOYEE_ID[_e.first_name] = _e.employee_id

# ---------------------------------------------------------------------------
# Court master  (ER: CourtID, CourtName, DistrictID, StateID, Active)
# ---------------------------------------------------------------------------
@dataclass
class KSPCourt:
    court_id: int
    court_name: str
    district_id: int
    state_id: int = STATE_ID_KARNATAKA
    active: int = 1

COURTS: List[KSPCourt] = [
    KSPCourt(7001, "Court of Additional Chief Metropolitan Magistrate, Bengaluru", 2901),
    KSPCourt(7002, "Court of Chief Judicial Magistrate, Bengaluru",               2901),
    KSPCourt(7003, "Court of Chief Judicial Magistrate, Mysuru",                  2903),
    KSPCourt(7004, "Court of Chief Judicial Magistrate, Mangaluru",               2904),
    KSPCourt(7005, "Court of Chief Judicial Magistrate, Hubballi",                2905),
    KSPCourt(7006, "Court of Chief Judicial Magistrate, Belagavi",                2906),
    KSPCourt(7007, "Court of Chief Judicial Magistrate, Dharwad",                 2919),
    KSPCourt(7008, "Court of Chief Judicial Magistrate, Tumakuru",                2911),
    KSPCourt(7009, "Court of Chief Judicial Magistrate, Kalaburagi",              2907),
    KSPCourt(7010, "Court of Chief Judicial Magistrate, Shivamogga",              2909),
]
DISTRICT_TO_COURT_ID: Dict[int, int] = {c.district_id: c.court_id for c in COURTS}
COURT_MAP: Dict[int, KSPCourt] = {c.court_id: c for c in COURTS}

# ---------------------------------------------------------------------------
# CaseCategory master  (ER: CaseCategoryID, LookupValue)
# ---------------------------------------------------------------------------
@dataclass
class KSPCaseCategory:
    case_category_id: int
    lookup_value: str
    # Internal helper: numeric code used in CrimeNo format (not an ER column)
    _category_code: int = 1

CASE_CATEGORIES: List[KSPCaseCategory] = [
    KSPCaseCategory(1, "FIR",      1),
    KSPCaseCategory(3, "UDR",      3),
    KSPCaseCategory(4, "PAR",      4),
    KSPCaseCategory(8, "Zero FIR", 8),
]
CASE_CATEGORY_MAP: Dict[str, int] = {c.lookup_value: c.case_category_id for c in CASE_CATEGORIES}
CASE_CATEGORY_CODE_MAP: Dict[int, int] = {c._category_code: c.case_category_id for c in CASE_CATEGORIES}

# ---------------------------------------------------------------------------
# GravityOffence master  (ER: GravityOffenceID, LookupValue)
# ---------------------------------------------------------------------------
@dataclass
class KSPGravityOffence:
    gravity_offence_id: int
    lookup_value: str

GRAVITY_OFFENCES: List[KSPGravityOffence] = [
    KSPGravityOffence(1, "Heinous"),
    KSPGravityOffence(2, "Non-Heinous"),
    KSPGravityOffence(3, "Economic Offence"),
]
GRAVITY_MAP: Dict[str, int] = {g.lookup_value: g.gravity_offence_id for g in GRAVITY_OFFENCES}
DEFAULT_GRAVITY_ID = 3   # Economic Offence for financial cyber crimes

# ---------------------------------------------------------------------------
# CaseStatusMaster  (ER: CaseStatusID, CaseStatusName)
# ---------------------------------------------------------------------------
@dataclass
class KSPCaseStatus:
    case_status_id: int
    case_status_name: str

CASE_STATUSES: List[KSPCaseStatus] = [
    KSPCaseStatus(1, "Under Investigation"),
    KSPCaseStatus(2, "Charge Sheeted"),
    KSPCaseStatus(3, "Undetected"),
    KSPCaseStatus(4, "Closed"),
    KSPCaseStatus(5, "Referred"),
]
CASE_STATUS_MAP: Dict[str, int] = {s.case_status_name: s.case_status_id for s in CASE_STATUSES}

# ---------------------------------------------------------------------------
# CrimeHead  (ER: CrimeHeadID, CrimeGroupName, Active)
# CrimeSubHead  (ER: CrimeSubHeadID, CrimeHeadID, CrimeHeadName, SeqID)
#   + internal helper: crime_type_code (NOT exported to ER CSV)
# ---------------------------------------------------------------------------
@dataclass
class KSPCrimeHead:
    crime_head_id: int
    crime_group_name: str
    active: int = 1

@dataclass
class KSPCrimeSubHead:
    crime_sub_head_id: int
    crime_head_id: int
    crime_head_name: str   # ER column name (confusingly named but matches ER)
    seq_id: int = 0
    active: int = 1
    crime_type_code: str = ""  # internal helper — NOT exported to ER CSV

CRIME_HEADS: List[KSPCrimeHead] = [
    KSPCrimeHead(101, "Cyber Crime"),
    KSPCrimeHead(102, "Economic Offences"),
]
CRIME_HEAD_MAP: Dict[str, int] = {h.crime_group_name: h.crime_head_id for h in CRIME_HEADS}

CRIME_SUB_HEADS: List[KSPCrimeSubHead] = [
    KSPCrimeSubHead(1011, 101, "Digital Arrest / Fake Official Threat",  1,  1, "digital_arrest"),
    KSPCrimeSubHead(1012, 101, "Fake Investment / Stock Market Fraud",   2,  1, "investment_scam"),
    KSPCrimeSubHead(1013, 101, "Online Task / Job Scam",                 3,  1, "task_scam"),
    KSPCrimeSubHead(1014, 101, "UPI Payment Fraud",                      4,  1, "upi_fraud"),
    KSPCrimeSubHead(1015, 101, "OTP Theft / SIM Swap Fraud",             5,  1, "otp_fraud"),
    KSPCrimeSubHead(1016, 101, "Predatory Loan App Fraud",               6,  1, "loan_app"),
    KSPCrimeSubHead(1017, 101, "Fake Job / Placement Fraud",             7,  1, "job_scam"),
    KSPCrimeSubHead(1018, 101, "Sextortion / Honey Trap",                8,  1, "sextortion"),
    KSPCrimeSubHead(1019, 101, "Phishing / Vishing / Fake Bank",         9,  1, "phishing"),
    KSPCrimeSubHead(1020, 102, "Mule Account / Money Mule Recruitment",  10, 1, "mule_account"),
]
CRIME_TYPE_TO_SUB_HEAD_ID: Dict[str, int] = {s.crime_type_code: s.crime_sub_head_id for s in CRIME_SUB_HEADS}
CRIME_TYPE_TO_HEAD_ID: Dict[str, int] = {s.crime_type_code: s.crime_head_id for s in CRIME_SUB_HEADS}

# ---------------------------------------------------------------------------
# Act / Section master  (ER: VARCHAR PKs)
# Act:     ActCode (PK VARCHAR), ActDescription, ShortName, Active
# Section: ActCode (FK), SectionCode (VARCHAR), SectionDescription, Active
# ---------------------------------------------------------------------------
@dataclass
class KSPAct:
    act_code: str          # VARCHAR PK
    act_description: str
    short_name: str = ""
    active: int = 1

@dataclass
class KSPSection:
    act_code: str          # VARCHAR FK -> Act.ActCode
    section_code: str      # VARCHAR (part of composite PK with ActCode)
    section_description: str
    active: int = 1

ACTS: List[KSPAct] = [
    KSPAct("ITACT",  "Information Technology Act, 2000",          "IT Act",  1),
    KSPAct("BNS",    "Bharatiya Nyaya Sanhita, 2023",             "BNS",     1),
    KSPAct("PMLA",   "Prevention of Money Laundering Act, 2002",  "PMLA",    1),
    KSPAct("BSA",    "Bharatiya Sakshya Adhiniyam, 2023",         "BSA",     1),
    KSPAct("BNSS",   "Bharatiya Nagarik Suraksha Sanhita, 2023",  "BNSS",    1),
]
ACT_MAP: Dict[str, KSPAct] = {a.act_code: a for a in ACTS}

SECTIONS: List[KSPSection] = [
    KSPSection("ITACT","66C", "Punishment for identity theft - fraudulently or dishonestly using the electronic signature, password or unique identification feature of any other person.", 1),
    KSPSection("ITACT","66D", "Punishment for cheating by personation by using computer resource - cheating by personation using any communication device or computer resource.", 1),
    KSPSection("ITACT","43",  "Penalty and compensation for damage to computer, computer system, including unauthorised access and data theft.", 1),
    KSPSection("ITACT","72",  "Disclosure of information in breach of lawful contract by persons having secured access to electronic records.", 1),
    KSPSection("BNS",  "318", "Cheating - Whoever, by deceiving any person, fraudulently or dishonestly induces the person so deceived to deliver any property.", 1),
    KSPSection("BNS",  "319", "Cheating by personation - A person cheats by pretending to be some other person, or by knowingly substituting one person for another.", 1),
    KSPSection("PMLA", "3",   "Offence of money-laundering - Whosoever directly or indirectly attempts to indulge or knowingly assists in any process connected with the proceeds of crime.", 1),
    KSPSection("BSA",  "63",  "Admissibility of electronic records - An electronic record shall be admissible as evidence if it satisfies the conditions specified in this section.", 1),
    KSPSection("BNSS", "94",  "Power to issue summons - Every Court may send a summons to any person or authority in electronic form.", 1),
    KSPSection("BNSS", "175", "Power to issue search warrant - Power to issue warrant to search for or inspect any document or thing.", 1),
]
# Key: (act_code, section_code)
SECTION_MAP: Dict[tuple, KSPSection] = {(s.act_code, s.section_code): s for s in SECTIONS}

# ---------------------------------------------------------------------------
# CrimeHeadActSection  (ER: CrimeHeadID, ActCode, SectionCode)
# ---------------------------------------------------------------------------
@dataclass
class KSPCrimeHeadActSection:
    crime_head_id: int   # FK -> CrimeHead (ER uses CrimeHeadID, not CrimeSubHeadID)
    act_code: str
    section_code: str

CRIME_HEAD_ACT_SECTIONS: List[KSPCrimeHeadActSection] = [
    # Cyber Crime head -> IT Act sections
    KSPCrimeHeadActSection(101, "ITACT", "66C"),
    KSPCrimeHeadActSection(101, "ITACT", "66D"),
    KSPCrimeHeadActSection(101, "ITACT", "43"),
    KSPCrimeHeadActSection(101, "BNS",   "318"),
    KSPCrimeHeadActSection(101, "BNS",   "319"),
    # Economic Offences head
    KSPCrimeHeadActSection(102, "PMLA",  "3"),
    KSPCrimeHeadActSection(102, "BNS",   "318"),
]

# ---------------------------------------------------------------------------
# CasteMaster  (ER: caste_master_id, caste_master_name)
# ---------------------------------------------------------------------------
@dataclass
class KSPCaste:
    caste_master_id: int
    caste_master_name: str

CASTES: List[KSPCaste] = [
    KSPCaste(1, "General"),
    KSPCaste(2, "OBC"),
    KSPCaste(3, "SC"),
    KSPCaste(4, "ST"),
    KSPCaste(5, "Not Specified"),
]
CASTE_MAP: Dict[str, int] = {c.caste_master_name: c.caste_master_id for c in CASTES}

# ---------------------------------------------------------------------------
# ReligionMaster  (ER: ReligionID, ReligionName)
# ---------------------------------------------------------------------------
@dataclass
class KSPReligion:
    religion_id: int
    religion_name: str

RELIGIONS: List[KSPReligion] = [
    KSPReligion(1, "Hindu"),
    KSPReligion(2, "Muslim"),
    KSPReligion(3, "Christian"),
    KSPReligion(4, "Other"),
    KSPReligion(5, "Not Specified"),
]
RELIGION_MAP: Dict[str, int] = {r.religion_name: r.religion_id for r in RELIGIONS}

# ---------------------------------------------------------------------------
# OccupationMaster  (ER: OccupationID, OccupationName)
# ---------------------------------------------------------------------------
@dataclass
class KSPOccupation:
    occupation_id: int
    occupation_name: str

OCCUPATIONS: List[KSPOccupation] = [
    KSPOccupation(1, "Student"),
    KSPOccupation(2, "Doctor"),
    KSPOccupation(3, "Retired Professor"),
    KSPOccupation(4, "Retired Engineer"),
    KSPOccupation(5, "Retired IAS Officer"),
    KSPOccupation(6, "Chartered Accountant"),
    KSPOccupation(7, "Senior Manager"),
    KSPOccupation(8, "Businessman"),
    KSPOccupation(9, "Fresher"),
    KSPOccupation(10, "Part-time Worker"),
    KSPOccupation(11, "Job Seeker"),
    KSPOccupation(12, "Engineering Student"),
    KSPOccupation(13, "MBA Student"),
    KSPOccupation(14, "Unemployed Graduate"),
    KSPOccupation(15, "Software Engineer"),
    KSPOccupation(16, "IT Professional"),
    KSPOccupation(17, "Bank Employee"),
    KSPOccupation(18, "Teacher"),
    KSPOccupation(19, "Government Employee"),
    KSPOccupation(20, "Small Business Owner"),
    KSPOccupation(21, "Shop Owner"),
    KSPOccupation(22, "Trader"),
    KSPOccupation(23, "Contractor"),
    KSPOccupation(24, "Transport Operator"),
    KSPOccupation(25, "MSME Owner"),
    KSPOccupation(26, "Homemaker"),
    KSPOccupation(27, "Daily Wage Worker"),
    KSPOccupation(28, "Auto Driver"),
    KSPOccupation(29, "Delivery Worker"),
    KSPOccupation(30, "Unemployed"),
    KSPOccupation(31, "Freelancer"),
    KSPOccupation(32, "Small Trader"),
    KSPOccupation(33, "Call Centre Agent"),
    KSPOccupation(34, "Data Entry Operator"),
    KSPOccupation(35, "Money Lender"),
    KSPOccupation(36, "Property Dealer"),
    KSPOccupation(37, "Consultant"),
    KSPOccupation(38, "Finance Broker"),
    KSPOccupation(39, "Other"),
]
OCCUPATION_MAP: Dict[str, int] = {o.occupation_name: o.occupation_id for o in OCCUPATIONS}

def get_occupation_id(occupation: str) -> int:
    return OCCUPATION_MAP.get(occupation, 39)

# NOTE: demographic analysis in the platform MUST segment only by
# age/gender/occupation/education — caste_master_id and religion_id are
# populated for schema conformance but EXCLUDED from analysis.

# ---------------------------------------------------------------------------
# CrimeNo / CaseNo formatting
# Format: C(1) + DistrictID(4) + UnitID(4) + Year(4) + Serial(5) = 18 digits
# Category codes: FIR=1, UDR=3, PAR=4, ZeroFIR=8
# ---------------------------------------------------------------------------
def format_crime_no(category_code: int, district_id: int, unit_id: int,
                    year: int, serial: int) -> str:
    return f"{category_code}{district_id:04d}{unit_id:04d}{year:04d}{serial:05d}"

def case_no_from_crime_no(crime_no: str) -> str:
    return crime_no[-9:]

_serial_counters: Dict[Tuple[int, int, int], int] = {}

def next_serial(unit_id: int, category_code: int, year: int) -> int:
    key = (unit_id, category_code, year)
    _serial_counters[key] = _serial_counters.get(key, 0) + 1
    return _serial_counters[key]

def reset_serials() -> None:
    _serial_counters.clear()

def peek_next_serial(unit_id: int, category_code: int, year: int) -> int:
    key = (unit_id, category_code, year)
    return _serial_counters.get(key, 0) + 1

def assign_crime_no(station_id: str, category_code: int, year: int) -> str:
    unit_id = STATION_ID_TO_UNIT_ID[station_id]
    district_id = UNIT_MAP[unit_id].district_id
    serial = next_serial(unit_id, category_code, year)
    return format_crime_no(category_code, district_id, unit_id, year, serial)


def export_serial_state() -> Dict[str, int]:
    """Serialize CrimeNo serial counters for durable resume."""
    return {f"{u}|{c}|{y}": v for (u, c, y), v in _serial_counters.items()}


def import_serial_state(state: Dict[str, int]) -> None:
    """Restore CrimeNo serial counters from durable checkpoint state."""
    _serial_counters.clear()
    for key, val in (state or {}).items():
        parts = str(key).split("|")
        if len(parts) != 3:
            continue
        unit_id, category_code, year = map(int, parts)
        _serial_counters[(unit_id, category_code, year)] = int(val)

def get_default_court_id(station_id: str) -> int:
    district_id = get_district_id_for_station(station_id)
    court_id = DISTRICT_TO_COURT_ID.get(district_id)
    return court_id if court_id is not None else 7001

def get_default_employee_id(station_id: str) -> int:
    unit_id = STATION_ID_TO_UNIT_ID.get(station_id)
    for emp in EMPLOYEES:
        if emp.unit_id == unit_id:
            return emp.employee_id
    return EMPLOYEES[0].employee_id

# ---------------------------------------------------------------------------
# Sections charged per crime type (canonical list for ActSectionAssociation)
# ---------------------------------------------------------------------------
CRIME_TYPE_SECTIONS: Dict[str, List[Tuple[str, str]]] = {
    "digital_arrest":  [("ITACT","66C"), ("ITACT","66D"), ("BNS","318"), ("BNS","319")],
    "investment_scam": [("ITACT","66D"), ("BNS","318"), ("PMLA","3")],
    "task_scam":       [("ITACT","66D"), ("BNS","318")],
    "upi_fraud":       [("ITACT","66C"), ("ITACT","66D"), ("BNS","318")],
    "otp_fraud":       [("ITACT","66C"), ("BNS","319")],
    "loan_app":        [("ITACT","66D"), ("BNS","318")],
    "job_scam":        [("ITACT","66D"), ("BNS","318"), ("BNS","319")],
    "sextortion":      [("ITACT","66C"), ("ITACT","66D"), ("BNS","318")],
    "phishing":        [("ITACT","66C"), ("ITACT","66D"), ("BNS","319")],
    "mule_account":    [("PMLA","3"),    ("BNS","318")],
}
