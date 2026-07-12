"""
scenario_2.py — Many Names, One Man (Scenario 2)

Plants 3 historical FIRs (loan_app 2024, otp_fraud early-2025, job_scam late-2025)
and preps the live FIR (investment_scam 2026).

CRITICAL: 4 SEPARATE Person nodes — NOT pre-merged.
Each alias node has USES edges to the SAME DEV_IMEI_02 / UPI_02 / PHONE_02.
The platform's entity resolution merges them at runtime.

A decoy Person node ("Imran Sheikh") has completely independent identifiers.
"""
from __future__ import annotations
import random
from datetime import datetime, timedelta

from .models import FIR, Person, Account, Device, Phone, UPI, Transaction, SubEvent
from .identifier_pool import (
    DEV_IMEI_02, UPI_02, PHONE_02,
    SCN2_ALIAS_NODES, SCN2_MULE_ACCS, SCN2_DECOY_PERSON
)
from .reference_data import DISTRICT_MAP, STATIONS_BY_DISTRICT, IO_OFFICERS
from .config import (
    RANDOM_SEED, SCN2_AMOUNTS,
    SOUTH_INDIAN_FIRST_NAMES_MALE, SOUTH_INDIAN_LAST_NAMES,
    DEMOGRAPHICS_BY_ROLE
)

rng = random.Random(RANDOM_SEED + 2)


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


# Escalating victim amounts matching SCN2_AMOUNTS
_HIST_CASES = [
    {
        "fir_id": "FIR_SCN2_H01",
        "fir_number": "CR-031/2024",
        "crime_type": "loan_app",
        "year": 2024,
        "alias_idx": 0,            # "Imraan Sheikh"
        "mule_acc_idx": 0,
        "district": "Bengaluru Urban",
        "victim_name": "Lakshmi Krishnamurthy",
        "victim_age": 34,
        "victim_gender": "Female",
        "victim_occ": "Software Engineer",
        "offence_date": datetime(2024, 8, 15),
        "amount": SCN2_AMOUNTS[0],  # ₹1.5L
        "sections_bns": ["BNS_318"],
        "sections_it":  ["IT_66C"],
        "bns_sections": ["BNS_318"],
        "it_act_sections": ["IT_43"],
    },
    {
        "fir_id": "FIR_SCN2_H02",
        "fir_number": "CR-007/2025",
        "crime_type": "otp_fraud",
        "year": 2025,
        "alias_idx": 1,            # "I. Shaikh"
        "mule_acc_idx": 1,
        "district": "Tumakuru",
        "victim_name": "Harish Patil",
        "victim_age": 28,
        "victim_gender": "Male",
        "victim_occ": "Bank Employee",
        "offence_date": datetime(2025, 3, 22),
        "amount": SCN2_AMOUNTS[1],  # ₹4L
        "bns_sections": ["BNS_318", "BNS_319"],
        "it_act_sections": ["IT_66C"],
    },
    {
        "fir_id": "FIR_SCN2_H03",
        "fir_number": "CR-045/2025",
        "crime_type": "job_scam",
        "year": 2025,
        "alias_idx": 2,            # "Imran Shek"
        "mule_acc_idx": 2,
        "district": "Bengaluru Urban",
        "victim_name": "Deepa Nair",
        "victim_age": 24,
        "victim_gender": "Female",
        "victim_occ": "Job Seeker",
        "offence_date": datetime(2025, 11, 10),
        "amount": SCN2_AMOUNTS[2],  # ₹8L
        "bns_sections": ["BNS_318"],
        "it_act_sections": ["IT_66D"],
    },
]


def _build_case(cd: dict) -> tuple[FIR, Person, Person, Account, list[Transaction], list[dict]]:
    """
    Returns fir, victim, accused (alias node), mule_account, transactions, uses_edges.
    """
    district = cd["district"]
    dist_obj = DISTRICT_MAP[district]
    lat, long = _jitter_coords(dist_obj.lat, dist_obj.long)
    pincode = rng.choice(dist_obj.pincodes)

    offence_dt = cd["offence_date"]
    registered_dt = offence_dt + timedelta(days=rng.randint(1, 7))

    # Victim
    victim_id = f"P_{cd['fir_id']}_VIC"
    victim = Person(
        person_id=victim_id,
        full_name=cd["victim_name"],
        age=cd["victim_age"],
        gender=cd["victim_gender"],
        address=f"{rng.randint(1,200)}, {rng.choice(['4th Cross','Ring Road','Main Street'])}, {district}",
        district=district,
        occupation=cd["victim_occ"],
        employment_status="Employed",
        role="victim",
        first_seen_date=registered_dt.strftime("%Y-%m-%d"),
    )

    # Accused alias node — address unknown at time of historical FIR (identified only in live demo)
    alias_def = SCN2_ALIAS_NODES[cd["alias_idx"]]
    accused = Person(
        person_id=alias_def["person_id"],
        full_name=alias_def["full_name"],
        aliases=[],
        age=rng.randint(25, 35),
        gender="Male",
        address=f"Last seen in {district} area (unverified)",
        district=district,          # last-known district from the FIR complaint
        occupation="Unemployed",
        role="caller",
        first_seen_date=registered_dt.strftime("%Y-%m-%d"),
    )

    # Mule account (only for historical cases, each has its own)
    mule_raw = SCN2_MULE_ACCS[cd["mule_acc_idx"]]
    mule_acc = Account(
        account_no=mule_raw["account_no"],
        bank=mule_raw["bank"],
        ifsc=mule_raw["ifsc"],
        branch_district=mule_raw["branch_district"],
        open_date=(offence_dt - timedelta(days=rng.randint(90, 180))).strftime("%Y-%m-%d"),
        kyc_name=f"Account Holder {cd['alias_idx']+1}",
        is_flagged_mule=True,
        activity_history=[
            {"timestamp": offence_dt.strftime("%Y-%m-%dT%H:%M"), "direction": "in", "amount": cd["amount"]},
            {"timestamp": (offence_dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"), "direction": "out", "amount": cd["amount"]},
        ],
    )

    # Transactions
    txns: list[Transaction] = [
        Transaction(
            txn_id=f"TXN_{cd['fir_id']}_V2M",
            from_account=f"VICTIM_ACC_{cd['fir_id']}",
            to_account=mule_raw["account_no"],
            amount=cd["amount"],
            timestamp=offence_dt.strftime("%Y-%m-%dT%H:%M"),
            channel=rng.choice(["UPI", "IMPS", "NEFT"]),
            linked_fir_id=cd["fir_id"],
            hop_role="collection",
            source_fir_id=cd["fir_id"],
        )
    ]

    # USES edges — each alias node USES the same shared identifiers
    uses_edges = [
        {
            "from_person_id": alias_def["person_id"],
            "to_object_id": f"DEV_{DEV_IMEI_02}",
            "object_type": "Device",
            "source_fir_id": cd["fir_id"],
            "observed_date": registered_dt.strftime("%Y-%m-%d"),
            "confidence": 0.9,
        },
        {
            "from_person_id": alias_def["person_id"],
            "to_object_id": f"UPI_{UPI_02}",
            "object_type": "UPI",
            "source_fir_id": cd["fir_id"],
            "observed_date": registered_dt.strftime("%Y-%m-%d"),
            "confidence": 1.0,
        },
        {
            "from_person_id": alias_def["person_id"],
            "to_object_id": f"PHONE_{PHONE_02}",
            "object_type": "Phone",
            "source_fir_id": cd["fir_id"],
            "observed_date": registered_dt.strftime("%Y-%m-%d"),
            "confidence": 1.0,
        },
    ]

    # Sub-events
    if cd["crime_type"] == "loan_app":
        sub_events = [
            SubEvent("loan app downloaded",          offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("harassing calls started",      (offence_dt + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("coerced payment made",         (offence_dt + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                    registered_dt.strftime("%Y-%m-%dT%H:%M")),
        ]
    elif cd["crime_type"] == "otp_fraud":
        sub_events = [
            SubEvent("fake bank call received",       offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("OTP shared under duress",       (offence_dt + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("account debit noticed",         (offence_dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                     registered_dt.strftime("%Y-%m-%dT%H:%M")),
        ]
    else:
        sub_events = [
            SubEvent("fake job offer received",      offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("registration fee paid",        (offence_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("multiple advance payments",    (offence_dt + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("contact lost",                 (offence_dt + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                    registered_dt.strftime("%Y-%m-%dT%H:%M")),
        ]

    fir = FIR(
        fir_id=cd["fir_id"],
        fir_number=cd["fir_number"],
        crime_type=cd["crime_type"],
        date_registered=registered_dt.strftime("%Y-%m-%d"),
        date_of_offence=offence_dt.strftime("%Y-%m-%d"),
        district=district,
        pincode=pincode,
        lat=lat,
        long=long,
        police_station=_pick_station(district),
        complainant_person_id=victim_id,
        accused_person_ids=[alias_def["person_id"]],
        amount_involved=cd["amount"],
        bns_sections=cd["bns_sections"],
        it_act_sections=cd["it_act_sections"],
        identifiers_mentioned={
            "phones": [PHONE_02],
            "accounts": [mule_raw["account_no"]],
            "upis": [UPI_02],
            "imeis": [],
            "ips": [],
            "wallets": [],
        },
        status="Under Investigation",
        io_officer=rng.choice(IO_OFFICERS),
        narrative_tier="C",   # different crime types — low mutual similarity
        sub_events=sub_events,
    )
    return fir, victim, accused, mule_acc, txns, uses_edges


def _build_shared_objects() -> tuple[Device, Phone, UPI]:
    device = Device(device_id=f"DEV_{DEV_IMEI_02}", imei=DEV_IMEI_02)
    phone = Phone(phone_id=f"PHONE_{PHONE_02}", number=PHONE_02)
    upi = UPI(upi_id=f"UPI_{UPI_02}", vpa=UPI_02)
    return device, phone, upi


def _build_decoy() -> tuple[Person, Device, Phone, UPI, Account]:
    """
    Decoy person — same-sounding name ('Imran Sheikh') but COMPLETELY independent identifiers.
    Entity resolution must reject the match.
    """
    dp = SCN2_DECOY_PERSON
    decoy_person = Person(
        person_id=dp["person_id"],
        full_name=dp["full_name"],
        aliases=[],
        age=rng.randint(25, 38),
        gender="Male",
        address="Different address entirely",
        district="Kalaburagi",
        occupation="Small Trader",
        role="operator",
        first_seen_date="2025-06-01",
    )
    decoy_device = Device(device_id=f"DEV_{dp['imei']}", imei=dp["imei"])
    decoy_phone  = Phone(phone_id=f"PHONE_{dp['phone']}", number=dp["phone"])
    decoy_upi    = UPI(upi_id=f"UPI_{dp['upi']}", vpa=dp["upi"])
    decoy_acc    = Account(
        account_no=dp["account_no"],
        bank="Bank of Baroda",
        ifsc="BARB0KALGBR",
        branch_district="Kalaburagi",
        open_date="2024-05-01",
        kyc_name="Imran Sheikh",
        is_flagged_mule=False,
    )
    return decoy_person, decoy_device, decoy_phone, decoy_upi, decoy_acc


def generate_scenario_2() -> dict:
    """
    Returns dict with keys: firs, persons, accounts, transactions,
    devices, phones, upis, uses_edges.
    Does NOT include the live FIR (handled by live_demo_generator.py).
    """
    firs: list[FIR] = []
    persons: list[Person] = []
    accounts: list[Account] = []
    transactions: list[Transaction] = []
    devices: list[Device] = []
    phones: list[Phone] = []
    upis: list[UPI] = []
    uses_edges: list[dict] = []

    for cd in _HIST_CASES:
        fir, victim, accused, mule_acc, txns, ue = _build_case(cd)
        firs.append(fir)
        persons.append(victim)
        persons.append(accused)
        accounts.append(mule_acc)
        transactions.extend(txns)
        uses_edges.extend(ue)

    # Shared objects
    shared_dev, shared_phone, shared_upi = _build_shared_objects()
    devices.append(shared_dev)
    phones.append(shared_phone)
    upis.append(shared_upi)

    # Decoy
    dp, dd, dph, du, da = _build_decoy()
    persons.append(dp)
    devices.append(dd)
    phones.append(dph)
    upis.append(du)
    accounts.append(da)

    return {
        "firs": firs,
        "persons": persons,
        "accounts": accounts,
        "transactions": transactions,
        "devices": devices,
        "phones": phones,
        "upis": upis,
        "uses_edges": uses_edges,
        "_ground_truth": {
            "alias_person_ids": [a["person_id"] for a in SCN2_ALIAS_NODES],
            "true_merged_case_count": 4,   # 3 historical + 1 live
            "shared_imei": DEV_IMEI_02,
            "shared_upi": UPI_02,
            "shared_phone": PHONE_02,
            "decoy_person_id": SCN2_DECOY_PERSON["person_id"],
            "decoy_note": "Same-sounding name but independent identifiers — must NOT resolve",
        },
    }
