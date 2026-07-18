"""Server-side allowlist for demo scenario mappings.

Only the four CrimeNos listed here are eligible for destructive prepare/reset.
CaseMaster stub defaults are aligned with each scenario's FIR header /
fir.expected.json and seeded masters in data_generation/ksp_master.py.

Unit IDs start at 1001. CrimeNo format:
  category(1) + district(4) + unit(4) + year(4) + serial(5) = 18 digits
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioMapping:
    key: str
    label: str
    crime_no: str
    case_no: str
    evidence_folder: str  # under sample_data/live_demo/evidence/
    police_station_id: int
    police_station_name: str
    district_id: int
    district_name: str
    police_person_id: int  # seeded Employee at (or for) that unit
    court_id: int
    crime_major_head_id: int
    crime_minor_head_id: int
    case_category_id: int = 1       # FIR
    gravity_offence_id: int = 3     # Economic Offence
    case_status_id: int = 1         # Under Investigation


# Fallback for non-scenario "new case" mints (CEN East / PI Venkatesh Kumar).
@dataclass(frozen=True)
class DemoCaseDefaults:
    police_person_id: int = 5001
    police_station_id: int = 1001
    case_category_id: int = 1
    gravity_offence_id: int = 3
    crime_major_head_id: int = 101
    crime_minor_head_id: int = 1011
    case_status_id: int = 1
    court_id: int = 7001
    case_no: str | None = None


DEFAULT_NEW_CASE = DemoCaseDefaults()


SCENARIO_ALLOWLIST: dict[str, ScenarioMapping] = {
    # FIR: CEN East, Bengaluru Urban — digital_arrest → CrimeSubHead 1011
    # CrimeNo 1|2901|1001|2026|90001; IO at unit 1001 = Employee 5001
    # (live serials use a reserved high band so they never collide with historical)
    "digital-arrest": ScenarioMapping(
        key="digital-arrest",
        label="Digital Arrest",
        crime_no="129011001202690001",
        case_no="202690001",
        evidence_folder="scenario_1",
        police_station_id=1001,
        police_station_name="CEN Police Station - East Division",
        district_id=2901,
        district_name="Bengaluru Urban",
        police_person_id=5001,  # Venkatesh Kumar @ 1001
        court_id=7001,          # ACMM Bengaluru
        crime_major_head_id=101,
        crime_minor_head_id=1011,
    ),
    # FIR: Whitefield Cyber, Bengaluru Urban — investment_scam → 1012
    # CrimeNo 1|2901|1005|2026|90002; IO at unit 1005 = Employee 5010
    "many-names": ScenarioMapping(
        key="many-names",
        label="Many Names, One Man",
        crime_no="129011005202690002",
        case_no="202690002",
        evidence_folder="scenario_2",
        police_station_id=1005,
        police_station_name="Whitefield Cyber Crime Police Station",
        district_id=2901,
        district_name="Bengaluru Urban",
        police_person_id=5010,  # Kavitha Reddy @ 1005
        court_id=7001,
        crime_major_head_id=101,
        crime_minor_head_id=1012,
    ),
    # FIR: Dharwad Cyber — investment_scam → 1012
    # CrimeNo 1|2919|1018|2026|90003; IO at unit 1018 = Employee 5007
    "follow-money": ScenarioMapping(
        key="follow-money",
        label="Follow The Money",
        crime_no="129191018202690003",
        case_no="202690003",
        evidence_folder="scenario_3",
        police_station_id=1018,
        police_station_name="Dharwad Cyber Crime Police Station",
        district_id=2919,
        district_name="Dharwad",
        police_person_id=5007,  # Deepa Kamath @ 1018
        court_id=7007,          # CJM Dharwad
        crime_major_head_id=101,
        crime_minor_head_id=1012,
    ),
    # FIR: CEN West, Bengaluru Urban — task_scam → 1013
    # CrimeNo 1|2901|1002|2026|90004; no Employee seeded at 1002 → district fallback 5001
    "surge": ScenarioMapping(
        key="surge",
        label="The Surge",
        crime_no="129011002202690004",
        case_no="202690004",
        evidence_folder="scenario_4",
        police_station_id=1002,
        police_station_name="CEN Police Station - West Division",
        district_id=2901,
        district_name="Bengaluru Urban",
        police_person_id=5001,  # no IO at unit 1002 in seed; same as ksp_master.get_default_employee_id fallback
        court_id=7001,
        crime_major_head_id=101,
        crime_minor_head_id=1013,
    ),
}


def is_allowed_scenario(key: str) -> bool:
    return key in SCENARIO_ALLOWLIST


def get_scenario(key: str) -> ScenarioMapping | None:
    return SCENARIO_ALLOWLIST.get(key)


def get_crime_no(key: str) -> str | None:
    mapping = SCENARIO_ALLOWLIST.get(key)
    return mapping.crime_no if mapping else None


def case_defaults_for(scenario_key: str | None) -> DemoCaseDefaults:
    """FK + case_no defaults for a CaseMaster stub insert."""
    if scenario_key:
        s = SCENARIO_ALLOWLIST.get(scenario_key)
        if s:
            return DemoCaseDefaults(
                police_person_id=s.police_person_id,
                police_station_id=s.police_station_id,
                case_category_id=s.case_category_id,
                gravity_offence_id=s.gravity_offence_id,
                crime_major_head_id=s.crime_major_head_id,
                crime_minor_head_id=s.crime_minor_head_id,
                case_status_id=s.case_status_id,
                court_id=s.court_id,
                case_no=s.case_no,
            )
    return DEFAULT_NEW_CASE
