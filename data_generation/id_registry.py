"""
id_registry.py - Deterministic logical-string-key -> INT PK mapping.

All IDs are assigned in a fixed, deterministic order so reruns are byte-identical.
The registry is the single source of truth for:
  - CaseMasterID  (base 1_000_000)
  - AccusedMasterID (base 2_000_000)
  - ComplainantID  (base 3_000_000)
  - VictimMasterID (base 4_000_000)
  - ReportID       (base 5_000_000)
  - extension obj IDs (base 6_000_000+)

Live-only entities (CTRL_*, live accused) are assigned IDs ONLY when
live_demo_generator.py projects their IR — never in historical data.

RESERVED LIVE CASES: 4 live FIRs have pre-assigned CrimeNo / PoliceStationID
so their FK resolves against the seeded Unit master on upload.
"""
from __future__ import annotations
from typing import Dict, Optional, Tuple
from . import ksp_master as km
# ---------------------------------------------------------------------------
# INT PK base ranges
# ---------------------------------------------------------------------------
CASE_MASTER_BASE    = 1_000_000
ACCUSED_BASE        = 2_000_000
COMPLAINANT_BASE    = 3_000_000
VICTIM_BASE         = 4_000_000
REPORT_BASE         = 5_000_000
EXT_OBJ_BASE        = 6_000_000   # accounts, phones, devices, UPI, IP, wallet

# ---------------------------------------------------------------------------
# ID Registry — internal counters and maps
# ---------------------------------------------------------------------------
_case_master_map:  Dict[str, int] = {}
_accused_map:      Dict[str, int] = {}
_complainant_map:  Dict[str, int] = {}
_victim_map:       Dict[str, int] = {}
_report_map:       Dict[str, int] = {}
_ext_obj_map:      Dict[str, int] = {}

_case_master_counter  = CASE_MASTER_BASE
_accused_counter      = ACCUSED_BASE
_complainant_counter  = COMPLAINANT_BASE
_victim_counter       = VICTIM_BASE
_report_counter       = REPORT_BASE
_ext_obj_counter      = EXT_OBJ_BASE

def reset_registry() -> None:
    """Clear all maps and reset counters. Call once at pipeline start."""
    global _case_master_counter, _accused_counter, _complainant_counter
    global _victim_counter, _report_counter, _ext_obj_counter
    _case_master_map.clear()
    _accused_map.clear()
    _complainant_map.clear()
    _victim_map.clear()
    _report_map.clear()
    _ext_obj_map.clear()
    _case_master_counter  = CASE_MASTER_BASE
    _accused_counter      = ACCUSED_BASE
    _complainant_counter  = COMPLAINANT_BASE
    _victim_counter       = VICTIM_BASE
    _report_counter       = REPORT_BASE
    _ext_obj_counter      = EXT_OBJ_BASE

# --- CaseMaster ---
def case_master_id(fir_logical_id: str) -> int:
    global _case_master_counter
    if fir_logical_id not in _case_master_map:
        _case_master_counter += 1
        _case_master_map[fir_logical_id] = _case_master_counter
    return _case_master_map[fir_logical_id]

def get_case_master_id(fir_logical_id: str) -> Optional[int]:
    return _case_master_map.get(fir_logical_id)

# --- Accused ---
def accused_master_id(person_logical_id: str) -> int:
    global _accused_counter
    if person_logical_id not in _accused_map:
        _accused_counter += 1
        _accused_map[person_logical_id] = _accused_counter
    return _accused_map[person_logical_id]

def get_accused_master_id(person_logical_id: str) -> Optional[int]:
    return _accused_map.get(person_logical_id)

# --- Complainant ---
def complainant_id(person_logical_id: str) -> int:
    global _complainant_counter
    if person_logical_id not in _complainant_map:
        _complainant_counter += 1
        _complainant_map[person_logical_id] = _complainant_counter
    return _complainant_map[person_logical_id]

def get_complainant_id(person_logical_id: str) -> Optional[int]:
    return _complainant_map.get(person_logical_id)

# --- Victim ---
def victim_master_id(person_logical_id: str) -> int:
    global _victim_counter
    if person_logical_id not in _victim_map:
        _victim_counter += 1
        _victim_map[person_logical_id] = _victim_counter
    return _victim_map[person_logical_id]

def get_victim_master_id(person_logical_id: str) -> Optional[int]:
    return _victim_map.get(person_logical_id)

# --- Investigation Report ---
def report_id(report_logical_id: str) -> int:
    global _report_counter
    if report_logical_id not in _report_map:
        _report_counter += 1
        _report_map[report_logical_id] = _report_counter
    return _report_map[report_logical_id]

def get_report_id(report_logical_id: str) -> Optional[int]:
    return _report_map.get(report_logical_id)

# --- Extension objects (accounts, phones, devices, UPI, IP, wallet) ---
def ext_obj_id(obj_logical_id: str) -> int:
    global _ext_obj_counter
    if obj_logical_id not in _ext_obj_map:
        _ext_obj_counter += 1
        _ext_obj_map[obj_logical_id] = _ext_obj_counter
    return _ext_obj_map[obj_logical_id]

def get_ext_obj_id(obj_logical_id: str) -> Optional[int]:
    return _ext_obj_map.get(obj_logical_id)

# ---------------------------------------------------------------------------
# Resolver: translate a logical source_fir_id on an edge/transaction
# to its INT CaseMasterID (for export provenance fields)
# ---------------------------------------------------------------------------
def resolve_source_fir_id(logical_fir_id: str) -> Optional[int]:
    """
    Given a logical FIR string key (e.g. 'FIR_SCN1_H01'), return the
    CaseMasterID. Returns None if not yet registered (live-only FIR).
    """
    return _case_master_map.get(logical_fir_id)

# ---------------------------------------------------------------------------
# RESERVED LIVE CASES
# Pre-assign CrimeNo + PoliceStationID for the 4 live demo FIRs.
# These are reserved BEFORE historical assignments so the live CrimeNo
# is known at generation time (for the FIR header block) and never
# collides with historical CrimeNos.
#
# Each live FIR uses a SEEDED station that already exists in the Unit master.
# The CrimeNo is allocated via km.next_serial() during reserve_live_cases().
# ---------------------------------------------------------------------------

# Station assignments for live FIRs (using seeded units from ksp_master)
LIVE_SCENARIO_STATIONS = {
    "LIVE_SCN1": "PS_BLR_CEN_01",    # Bengaluru Urban - digital_arrest reveal
    "LIVE_SCN2": "PS_BLR_CYBER_01",  # Bengaluru Urban - entity resolution reveal
    "LIVE_SCN3": "PS_DWD_01",        # Dharwad - Follow the Money bridge reveal
    "LIVE_SCN4": "PS_BLR_CEN_02",    # Bengaluru Urban - surge continuation
}

LIVE_CASE_CATEGORY = 1   # FIR
LIVE_CASE_YEAR = 2026

# Live FIRs draw CrimeNo serials from a reserved HIGH band that historical minting
# can never reach. Historical serials start at 1 and, per (unit, category, year),
# never exceed a few dozen (max observed ~11), so a base of 90000 leaves a vast gap.
# This is what makes live CrimeNos collision-proof REGARDLESS of whether the
# historical CSVs are rebuilt in a separate process from the live reservation --
# previously they shared one counter, and a standalone historical rebuild (the
# documented `--stages sql_csv,db_load --no-resume` shortcut) restarted historical
# serials at 1 and reclaimed the live serial-1 slot, colliding with the already
# baked live FIRs (3 of 4 scenarios). Minting here does NOT advance the shared
# historical counter (km.next_serial), so historical cases at the same station
# still get serial 1, 2, 3 ...
# ponytail: ceiling is <90000 historical cases per (unit, category, year). True by
# ~4 orders of magnitude today; if a station ever exceeds it, widen the band.
LIVE_SERIAL_BASE = 90000

# Populated by reserve_live_cases(); exported to manifest
_live_reserved: Dict[str, Dict] = {}

def reserve_live_cases() -> Dict[str, Dict]:
    """
    Pre-assign CrimeNo/CaseNo/UnitID/DistrictID for the 4 live FIRs.
    Must be called ONCE, before historical case registration begins,
    so the live CrimeNos can appear in fir.txt header blocks.
    Returns the reservation map (also stored in _live_reserved).
    """
    _live_reserved.clear()
    for index, (scenario_key, station_id) in enumerate(LIVE_SCENARIO_STATIONS.items(), start=1):
        unit_id = km.STATION_ID_TO_UNIT_ID[station_id]
        district_id = km.UNIT_MAP[unit_id].district_id
        serial = LIVE_SERIAL_BASE + index
        # Mint directly so the shared historical serial counter is NOT advanced.
        crime_no = km.format_crime_no(LIVE_CASE_CATEGORY, district_id, unit_id, LIVE_CASE_YEAR, serial)
        case_no = km.case_no_from_crime_no(crime_no)
        _live_reserved[scenario_key] = {
            "station_id":  station_id,
            "unit_id":     unit_id,
            "district_id": district_id,
            "crime_no":    crime_no,
            "case_no":     case_no,
        }
    return dict(_live_reserved)

def get_live_reservation(scenario_key: str) -> Dict:
    """Return the reservation dict for a live scenario key."""
    if not _live_reserved:
        raise RuntimeError("reserve_live_cases() must be called before accessing reservations.")
    return _live_reserved[scenario_key]

def get_all_live_reservations() -> Dict[str, Dict]:
    return dict(_live_reserved)

# ---------------------------------------------------------------------------
# Bulk introspection (for manifest generation)
# ---------------------------------------------------------------------------
def all_case_ids() -> Dict[str, int]:
    return dict(_case_master_map)

def all_accused_ids() -> Dict[str, int]:
    return dict(_accused_map)

def all_complainant_ids() -> Dict[str, int]:
    return dict(_complainant_map)

def all_victim_ids() -> Dict[str, int]:
    return dict(_victim_map)

def all_report_ids() -> Dict[str, int]:
    return dict(_report_map)


def export_state() -> Dict:
    """Serialize registry state for durable resume checkpoints."""
    return {
        "case_master_map": dict(_case_master_map),
        "accused_map": dict(_accused_map),
        "complainant_map": dict(_complainant_map),
        "victim_map": dict(_victim_map),
        "report_map": dict(_report_map),
        "ext_obj_map": dict(_ext_obj_map),
        "case_master_counter": _case_master_counter,
        "accused_counter": _accused_counter,
        "complainant_counter": _complainant_counter,
        "victim_counter": _victim_counter,
        "report_counter": _report_counter,
        "ext_obj_counter": _ext_obj_counter,
        "live_reserved": dict(_live_reserved),
    }


def import_state(state: Dict) -> None:
    """Restore registry maps/counters from durable checkpoint state."""
    global _case_master_counter, _accused_counter, _complainant_counter
    global _victim_counter, _report_counter, _ext_obj_counter

    _case_master_map.clear()
    _case_master_map.update({k: int(v) for k, v in (state.get("case_master_map") or {}).items()})
    _accused_map.clear()
    _accused_map.update({k: int(v) for k, v in (state.get("accused_map") or {}).items()})
    _complainant_map.clear()
    _complainant_map.update({k: int(v) for k, v in (state.get("complainant_map") or {}).items()})
    _victim_map.clear()
    _victim_map.update({k: int(v) for k, v in (state.get("victim_map") or {}).items()})
    _report_map.clear()
    _report_map.update({k: int(v) for k, v in (state.get("report_map") or {}).items()})
    _ext_obj_map.clear()
    _ext_obj_map.update({k: int(v) for k, v in (state.get("ext_obj_map") or {}).items()})

    _case_master_counter = int(state.get("case_master_counter", CASE_MASTER_BASE))
    _accused_counter = int(state.get("accused_counter", ACCUSED_BASE))
    _complainant_counter = int(state.get("complainant_counter", COMPLAINANT_BASE))
    _victim_counter = int(state.get("victim_counter", VICTIM_BASE))
    _report_counter = int(state.get("report_counter", REPORT_BASE))
    _ext_obj_counter = int(state.get("ext_obj_counter", EXT_OBJ_BASE))

    _live_reserved.clear()
    _live_reserved.update(state.get("live_reserved") or {})
