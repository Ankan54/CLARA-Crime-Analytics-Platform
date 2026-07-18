"""
scenario_1.py — Digital Arrest Ring (Scenario 1)

Plants 3 historical FIRs (Mysuru, Mangaluru, Hubballi-Dharwad) with Tier-A narratives.
All route funds through collection accounts → AGG_ACC_01.
Controller (CTRL_IMEI_01 / CTRL_UPI_01) is ABSENT from historical data.
AGG_ACC_01 has no kyc_name and no owner Person node until the live IR is ingested.

One decoy FIR (TRAI hybrid) is also generated here — similar enough to surface in search
but with ZERO shared identifiers with the ring cases.
"""
from __future__ import annotations
import uuid
import random
from datetime import datetime, timedelta

from .models import FIR, Person, Account, Transaction, Device, Phone, UPI, SubEvent
from .identifier_pool import (
    AGG_ACC_01, SCN1_COLLECT_ACCS, SCN1_DECOY,
    SCN1_MULE_KYC_NAME, SCN1_MULE_AADHAAR
)
from .reference_data import DISTRICT_MAP, STATIONS_BY_DISTRICT, IO_OFFICERS
from .config import (
    RANDOM_SEED, DEMO_DATE_STR, SCN1_CASHOUT_WINDOW_MINUTES,
    SOUTH_INDIAN_FIRST_NAMES_MALE, SOUTH_INDIAN_FIRST_NAMES_FEMALE, SOUTH_INDIAN_LAST_NAMES,
    DEMOGRAPHICS_BY_ROLE
)

rng = random.Random(RANDOM_SEED + 1)   # seeded, deterministic


def _make_fir_number(district_code: str, seq: int) -> str:
    return f"CR-{seq:03d}/2026"


def _jitter_coords(lat: float, long: float) -> tuple[float, float]:
    return (
        round(lat + rng.uniform(-0.05, 0.05), 6),
        round(long + rng.uniform(-0.05, 0.05), 6),
    )


def _pick_station(district: str) -> str:
    stations = STATIONS_BY_DISTRICT.get(district, [])
    if not stations:
        return "PS_BLR_CEN_01"
    return rng.choice(stations).station_id


def _pick_io() -> str:
    return rng.choice(IO_OFFICERS)


def _rand_date(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(seconds=rng.randint(0, int(delta.total_seconds())))


def _victim_name() -> str:
    first = rng.choice(SOUTH_INDIAN_FIRST_NAMES_MALE + SOUTH_INDIAN_FIRST_NAMES_FEMALE)
    last = rng.choice(SOUTH_INDIAN_LAST_NAMES)
    return f"{first} {last}"


def _victim_age() -> int:
    lo, hi = DEMOGRAPHICS_BY_ROLE["victim_digital_arrest"]["age_range"]
    return rng.randint(lo, hi)


def _occupation() -> str:
    return rng.choice(DEMOGRAPHICS_BY_ROLE["victim_digital_arrest"]["occupations"])


# Demo date
DEMO_DT = datetime.strptime(DEMO_DATE_STR, "%Y-%m-%d")

# Coordinated cash-out window: all 4 cases within 2 hours on April 14 2026
CASHOUT_BASE = datetime(2026, 4, 14, 10, 0, 0)


# ---------------------------------------------------------------------------
# CASE DATA for the 3 historical FIRs
# ---------------------------------------------------------------------------
_HIST_CASES = [
    {
        "fir_id": "FIR_SCN1_H01",
        "seq": 12,
        "district": "Mysuru",
        "victim_name": "Suresh Venkataraman",
        "victim_age": 61,
        "occupation": "Retired IAS Officer",
        "gender": "Male",
        "amount": 2100000,   # ₹21L
        "num_transfers": 3,
        "channel": "NEFT",
        "offence_date": datetime(2026, 4, 14, 10, 15, 0),
        "collect_acc_idx": 0,
        "fir_number": "CR-012/2026",
    },
    {
        "fir_id": "FIR_SCN1_H02",
        "seq": 18,
        "district": "Mangaluru",
        "victim_name": "Priya Kamath",
        "victim_age": 54,
        "occupation": "Chartered Accountant",
        "gender": "Female",
        "amount": 1800000,   # ₹18L
        "num_transfers": 2,
        "channel": "IMPS",
        "offence_date": datetime(2026, 4, 14, 10, 45, 0),
        "collect_acc_idx": 1,
        "fir_number": "CR-018/2026",
    },
    {
        "fir_id": "FIR_SCN1_H03",
        "seq": 24,
        "district": "Hubballi-Dharwad",
        "victim_name": "Manjunath Hegde",
        "victim_age": 67,
        "occupation": "Retired Engineer",
        "gender": "Male",
        "amount": 1500000,   # ₹15L
        "num_transfers": 4,
        "channel": "UPI",
        "offence_date": datetime(2026, 4, 14, 11, 30, 0),
        "collect_acc_idx": 2,
        "fir_number": "CR-024/2026",
    },
]


def _build_case(case_data: dict) -> tuple[FIR, Person, Account, list[Transaction]]:
    """Build one historical digital-arrest FIR with victim, collection account, and transactions."""
    district = case_data["district"]
    dist_obj = DISTRICT_MAP[district]
    lat, long = _jitter_coords(dist_obj.lat, dist_obj.long)
    pincode = rng.choice(dist_obj.pincodes)

    registered_dt = case_data["offence_date"] + timedelta(days=rng.randint(1, 5))

    # Victim person
    victim_id = f"P_{case_data['fir_id']}_VIC"
    victim = Person(
        person_id=victim_id,
        full_name=case_data["victim_name"],
        age=case_data["victim_age"],
        gender=case_data["gender"],
        address=f"{rng.randint(1,100)}, {rng.choice(['MG Road','Brigade Road','Rajajinagar','Jayanagar'])} Layout, {district}",
        district=district,
        education="Graduate",
        occupation=case_data["occupation"],
        employment_status="Retired" if "Retired" in case_data["occupation"] else "Employed",
        role="victim",
        first_seen_date=registered_dt.strftime("%Y-%m-%d"),
        kyc_ids={"pan": f"ABCDE{rng.randint(1000,9999)}F", "aadhaar_synth": f"{rng.randint(1000,9999)} {rng.randint(1000,9999)} {rng.randint(1000,9999)}"},
    )

    # Collection account (each case has its own)
    coll_raw = SCN1_COLLECT_ACCS[case_data["collect_acc_idx"]]
    coll_acc = Account(
        account_no=coll_raw["account_no"],
        bank=coll_raw["bank"],
        ifsc=coll_raw["ifsc"],
        branch_district=coll_raw["branch_district"],
        open_date=_rand_date(datetime(2023, 1, 1), datetime(2024, 6, 1)).strftime("%Y-%m-%d"),
        kyc_name=f"Mule Account {case_data['collect_acc_idx']+1}",
        is_flagged_mule=True,
        activity_history=[
            {"timestamp": case_data["offence_date"].strftime("%Y-%m-%dT%H:%M"), "direction": "in",  "amount": case_data["amount"]},
            {"timestamp": (case_data["offence_date"] + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M"), "direction": "out", "amount": case_data["amount"]},
        ],
    )

    # Transactions: victim → collection → AGG_ACC_01
    txns: list[Transaction] = []
    amount_per = case_data["amount"] // case_data["num_transfers"]
    cashout_offset = max(20, min(SCN1_CASHOUT_WINDOW_MINUTES - 1, 28))
    for i in range(case_data["num_transfers"]):
        ts = case_data["offence_date"] + timedelta(minutes=i * 5)
        txns.append(Transaction(
            txn_id=f"TXN_{case_data['fir_id']}_V2C_{i+1}",
            from_account=f"VICTIM_ACC_{case_data['fir_id']}",
            to_account=coll_raw["account_no"],
            amount=amount_per,
            timestamp=ts.strftime("%Y-%m-%dT%H:%M"),
            channel=case_data["channel"],
            linked_fir_id=case_data["fir_id"],
            hop_role="origin",
            source_fir_id=case_data["fir_id"],
        ))
    # collection → AGG_ACC_01 (one consolidated transfer)
    txns.append(Transaction(
        txn_id=f"TXN_{case_data['fir_id']}_C2A",
        from_account=coll_raw["account_no"],
        to_account=AGG_ACC_01["account_no"],
        amount=case_data["amount"],
        timestamp=(case_data["offence_date"] + timedelta(minutes=cashout_offset)).strftime("%Y-%m-%dT%H:%M"),
        channel="IMPS",
        linked_fir_id=case_data["fir_id"],
        hop_role="aggregation",
        source_fir_id=case_data["fir_id"],
    ))

    # Sub-events
    sub_events = [
        SubEvent("call received from fake TRAI number",   case_data["offence_date"].strftime("%Y-%m-%dT%H:%M")),
        SubEvent("call transferred to fake CBI officer",  (case_data["offence_date"] + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("digital arrest initiated via Skype",    (case_data["offence_date"] + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("first fund transfer",                   (case_data["offence_date"] + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("fraud realised",                        (case_data["offence_date"] + timedelta(hours=rng.randint(2, 24))).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("FIR filed",                             registered_dt.strftime("%Y-%m-%dT%H:%M")),
    ]

    fir = FIR(
        fir_id=case_data["fir_id"],
        fir_number=case_data["fir_number"],
        crime_type="digital_arrest",
        date_registered=registered_dt.strftime("%Y-%m-%d"),
        date_of_offence=case_data["offence_date"].strftime("%Y-%m-%d"),
        district=district,
        pincode=pincode,
        lat=lat,
        long=long,
        police_station=_pick_station(district),
        complainant_person_id=victim_id,
        accused_person_ids=[],   # controller not yet identified
        amount_involved=case_data["amount"],
        bns_sections=["BNS_318", "BNS_319"],
        it_act_sections=["IT_66C", "IT_66D"],
        identifiers_mentioned={
            "phones": [],
            # Mention BOTH the collection account the victim paid AND the shared
            # aggregation account its trail converges on, so find_links_between_cases
            # (which matches a shared MENTIONS node) reveals the 4-cases-one-account
            # convergence — the marquee "these separate cases are one network" moment.
            "accounts": [coll_raw["account_no"], AGG_ACC_01["account_no"]],
            "upis": [],
            "imeis": [],
            "ips": [],
            "wallets": [],
        },
        status="Under Investigation",
        io_officer=_pick_io(),
        narrative_tier="A",
        sub_events=sub_events,
    )
    return fir, victim, coll_acc, txns


def _build_agg_account() -> Account:
    """AGG_ACC_01 — pre-loaded with no kyc_name, no owner."""
    return Account(
        account_no=AGG_ACC_01["account_no"],
        bank=AGG_ACC_01["bank"],
        ifsc=AGG_ACC_01["ifsc"],
        branch_district=AGG_ACC_01["branch_district"],
        open_date="2025-03-15",
        kyc_name="",           # deliberately blank
        is_flagged_mule=True,
        activity_history=[
            {"timestamp": "2026-04-14T10:58", "direction": "in",  "amount": 2100000},
            {"timestamp": "2026-04-14T11:13", "direction": "in",  "amount": 1800000},
            {"timestamp": "2026-04-14T12:00", "direction": "in",  "amount": 1500000},
        ],
    )


def _build_decoy() -> tuple[FIR, Person, Account]:
    """
    Decoy FIR — TRAI hybrid variant (international call routing fraud on Google Meet).
    Tier A/B borderline in narrative; ZERO shared identifiers with the ring cases.
    Must surface in top-k similarity search but 'Find Links' must return nothing.
    """
    district = "Hassan"
    dist_obj = DISTRICT_MAP[district]
    lat, long = _jitter_coords(dist_obj.lat, dist_obj.long)
    pincode = rng.choice(dist_obj.pincodes)

    offence_dt = datetime(2026, 3, 10, 14, 0, 0)
    registered_dt = offence_dt + timedelta(days=2)

    victim_id = "P_SCN1_DECOY_VIC"
    victim = Person(
        person_id=victim_id,
        full_name="Nagaraj Swamy",
        age=63,
        gender="Male",
        address="12, MG Road, Hassan",
        district=district,
        education="Graduate",
        occupation="Retired Manager",
        employment_status="Retired",
        role="victim",
        first_seen_date=registered_dt.strftime("%Y-%m-%d"),
    )

    decoy_acc = Account(
        account_no=SCN1_DECOY["account_no"],
        bank=SCN1_DECOY["bank"],
        ifsc=SCN1_DECOY["ifsc"],
        branch_district=SCN1_DECOY["branch_district"],
        open_date="2024-11-01",
        kyc_name="Decoy Mule Account",
        is_flagged_mule=True,
    )

    sub_events = [
        SubEvent("call from TRAI about call routing fraud",   offence_dt.strftime("%Y-%m-%dT%H:%M")),
        SubEvent("transferred to fake official on Google Meet", (offence_dt + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("fund transfer to RBI compliance account",   (offence_dt + timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("FIR filed",                                 registered_dt.strftime("%Y-%m-%dT%H:%M")),
    ]

    fir = FIR(
        fir_id="FIR_SCN1_DECOY",
        fir_number="CR-008/2026",
        crime_type="digital_arrest",
        date_registered=registered_dt.strftime("%Y-%m-%d"),
        date_of_offence=offence_dt.strftime("%Y-%m-%d"),
        district=district,
        pincode=pincode,
        lat=lat,
        long=long,
        police_station=_pick_station(district),
        complainant_person_id=victim_id,
        accused_person_ids=[],
        amount_involved=980000,
        bns_sections=["BNS_318", "BNS_319"],
        it_act_sections=["IT_66C", "IT_66D"],
        identifiers_mentioned={
            "phones": [],
            "accounts": [SCN1_DECOY["account_no"]],
            "upis": [],
            "imeis": [],
            "ips": [],
            "wallets": [],
        },
        status="Under Investigation",
        io_officer=_pick_io(),
        narrative_tier="decoy",
        sub_events=sub_events,
    )
    return fir, victim, decoy_acc


def generate_scenario_1() -> dict:
    """
    Returns dict with keys: firs, persons, accounts, transactions.
    Does NOT include the live FIR (handled by live_demo_generator.py).
    """
    firs: list[FIR] = []
    persons: list[Person] = []
    accounts: list[Account] = []
    transactions: list[Transaction] = []

    # 3 historical ring cases
    for cd in _HIST_CASES:
        fir, victim, coll_acc, txns = _build_case(cd)
        firs.append(fir)
        persons.append(victim)
        accounts.append(coll_acc)
        transactions.extend(txns)

    # Aggregation account (shared hub — no owner)
    accounts.append(_build_agg_account())

    # Decoy case
    decoy_fir, decoy_vic, decoy_acc = _build_decoy()
    firs.append(decoy_fir)
    persons.append(decoy_vic)
    accounts.append(decoy_acc)

    return {
        "firs": firs,
        "persons": persons,
        "accounts": accounts,
        "transactions": transactions,
        # Ground truth for planted_links.md
        "_ground_truth": {
            "ring_fir_ids": ["FIR_SCN1_H01", "FIR_SCN1_H02", "FIR_SCN1_H03"],
            "agg_acc": AGG_ACC_01["account_no"],
            "decoy_fir_id": "FIR_SCN1_DECOY",
            "live_fir_id": "FIR_SCN1_LIVE",   # added by live_demo_generator
            "ctrl_imei": "CTRL_IMEI_01 — live-only",
            "ctrl_upi": "CTRL_UPI_01 — live-only",
            "mule_name": SCN1_MULE_KYC_NAME,
        },
    }
