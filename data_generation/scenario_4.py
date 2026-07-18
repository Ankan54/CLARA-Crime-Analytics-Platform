"""
scenario_4.py — The Surge (Scenario 4)

Plants:
  - 14 burst task_scam FIRs in the last 21 days (June 5–26, 2026) — Tier-A narratives
  - 5 baseline task_scam FIRs spread Jan–May 2026 — Tier-B narratives + INDEPENDENT identifiers
  - All burst cases share DEV_POOL_04, IP_POOL_04, MULE_SET_04 / MULE_UPI_04

Controller identifiers (SCN4_CONTROLLER_UPI, SCN4_CONTROLLER_ACC) are LIVE-ONLY —
revealed only in the live IR from the seized device dump.
"""
from __future__ import annotations
import random
from datetime import datetime, timedelta

from .models import FIR, Person, Account, Device, Phone, UPI, IP, Transaction, SubEvent
from .identifier_pool import (
    DEV_POOL_04, IP_POOL_04, MULE_SET_04, MULE_UPI_04,
    SCN4_OPERATORS
)
from .reference_data import DISTRICT_MAP, STATIONS_BY_DISTRICT, IO_OFFICERS
from .config import (
    RANDOM_SEED, DEMO_DATE_STR, SCN4_BURST_FIRS, SCN4_BASELINE_FIRS,
    SOUTH_INDIAN_FIRST_NAMES_MALE, SOUTH_INDIAN_FIRST_NAMES_FEMALE,
    SOUTH_INDIAN_LAST_NAMES, DEMOGRAPHICS_BY_ROLE
)

rng = random.Random(RANDOM_SEED + 4)
DEMO_DT = datetime.strptime(DEMO_DATE_STR, "%Y-%m-%d")

# Burst window: last 21 days
BURST_START = DEMO_DT - timedelta(days=21)

# Baseline window: Jan–May 2026
BASELINE_START = datetime(2026, 1, 1)
BASELINE_END   = datetime(2026, 5, 31)

# Districts for Bengaluru-heavy surge victims
_BLR_DISTRICTS = [
    "Bengaluru Urban", "Bengaluru Urban", "Bengaluru Urban",
    "Bengaluru Urban", "Bengaluru Rural",
]
_OTHER_DISTRICTS = [
    "Mysuru", "Tumakuru", "Mangaluru", "Shivamogga", "Davanagere",
    "Hassan", "Hubballi-Dharwad", "Kolar", "Chikkaballapur",
]


def _jitter(lat: float, long: float) -> tuple[float, float]:
    return (
        round(lat + rng.uniform(-0.05, 0.05), 6),
        round(long + rng.uniform(-0.05, 0.05), 6),
    )


def _pick_station(district: str) -> str:
    stations = STATIONS_BY_DISTRICT.get(district, [])
    return rng.choice(stations).station_id if stations else "PS_BLR_CEN_01"


def _victim_name() -> str:
    first = rng.choice(SOUTH_INDIAN_FIRST_NAMES_MALE + SOUTH_INDIAN_FIRST_NAMES_FEMALE)
    last = rng.choice(SOUTH_INDIAN_LAST_NAMES)
    return f"{first} {last}"


def _victim_age() -> int:
    lo, hi = DEMOGRAPHICS_BY_ROLE["victim_task_scam"]["age_range"]
    return rng.randint(lo, hi)


def _victim_occ() -> str:
    return rng.choice(DEMOGRAPHICS_BY_ROLE["victim_task_scam"]["occupations"])


def _rand_dt(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(seconds=rng.randint(0, int(delta.total_seconds())))


def _build_burst_fir(seq: int) -> tuple[FIR, Person, list[dict], list[dict]]:
    """One burst FIR (Tier-A narrative, shared pool identifiers)."""
    # Victim district — Bengaluru heavy
    district = rng.choice(_BLR_DISTRICTS + _OTHER_DISTRICTS)
    dist_obj = DISTRICT_MAP[district]
    lat, long = _jitter(dist_obj.lat, dist_obj.long)
    pincode = rng.choice(dist_obj.pincodes)

    offence_dt = _rand_dt(BURST_START, DEMO_DT - timedelta(days=1))
    registered_dt = offence_dt + timedelta(days=rng.randint(1, 4))

    fir_id = f"FIR_SCN4_BURST_{seq:02d}"
    victim_id = f"P_{fir_id}_VIC"
    victim_name = _victim_name()
    victim_age = _victim_age()
    victim_occ = _victim_occ()

    victim = Person(
        person_id=victim_id,
        full_name=victim_name,
        age=victim_age,
        gender=rng.choice(["Male", "Female"]),
        address=f"{rng.randint(1,200)}, {rng.choice(['1st Main','Cross Road','Colony Road'])}, {district}",
        district=district,
        occupation=victim_occ,
        employment_status="Student" if "Student" in victim_occ else "Seeking Employment",
        role="victim",
        first_seen_date=registered_dt.strftime("%Y-%m-%d"),
    )

    # Each burst case uses SOME pool identifiers (varied subset)
    mule_indices = rng.sample(range(len(MULE_SET_04)), k=rng.randint(2, 4))
    ip_idx = rng.randint(0, len(IP_POOL_04) - 1)
    dev_idx = rng.randint(0, len(DEV_POOL_04) - 1)

    used_mule_accs = [MULE_SET_04[i]["account_no"] for i in mule_indices]
    used_upi_ids   = [MULE_UPI_04[i] for i in mule_indices]

    amount = rng.randint(5000, 100000)
    num_deposits = rng.randint(2, 5)
    initial_deposit = rng.randint(500, 2000)

    sub_events = [
        SubEvent("Telegram task group invite",        offence_dt.strftime("%Y-%m-%dT%H:%M")),
        SubEvent("small test payment received",       (offence_dt + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("initial deposit paid",              (offence_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("withdrawal blocked",                (offence_dt + timedelta(days=rng.randint(2, 7))).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("contact lost with operators",       (offence_dt + timedelta(days=rng.randint(5, 10))).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("FIR filed",                         registered_dt.strftime("%Y-%m-%dT%H:%M")),
    ]

    fir = FIR(
        fir_id=fir_id,
        fir_number=f"CR-{200+seq:03d}/2026",
        crime_type="task_scam",
        date_registered=registered_dt.strftime("%Y-%m-%d"),
        date_of_offence=offence_dt.strftime("%Y-%m-%d"),
        district=district,
        pincode=pincode,
        lat=lat,
        long=long,
        police_station=_pick_station(district),
        complainant_person_id=victim_id,
        accused_person_ids=[],
        amount_involved=amount,
        bns_sections=["BNS_318"],
        it_act_sections=["IT_66C", "IT_66D"],
        identifiers_mentioned={
            "phones": [DEV_POOL_04[dev_idx][:10]],   # phone derived from IMEI for planting
            "accounts": used_mule_accs,
            "upis": used_upi_ids,
            "imeis": [DEV_POOL_04[dev_idx]],
            "ips": [IP_POOL_04[ip_idx]["ip"]],
            "wallets": [],
        },
        status="Under Investigation",
        io_officer=rng.choice(IO_OFFICERS),
        narrative_tier="A",
        sub_events=sub_events,
    )

    # MENTIONS edges data (to be converted to rels_mentions.csv by export.py)
    mentions = [
        {"from_fir_id": fir_id, "to_object_id": f"MULE_ACC_{acc}", "object_type": "Account",
         "source_fir_id": fir_id, "observed_date": registered_dt.strftime("%Y-%m-%d"), "confidence": 1.0}
        for acc in used_mule_accs
    ] + [
        {"from_fir_id": fir_id, "to_object_id": f"UPI_{upi}", "object_type": "UPI",
         "source_fir_id": fir_id, "observed_date": registered_dt.strftime("%Y-%m-%d"), "confidence": 1.0}
        for upi in used_upi_ids
    ] + [
        {"from_fir_id": fir_id, "to_object_id": f"IP_{IP_POOL_04[ip_idx]['ip']}", "object_type": "IP",
         "source_fir_id": fir_id, "observed_date": registered_dt.strftime("%Y-%m-%d"), "confidence": 0.8}
    ] + [
        {"from_fir_id": fir_id, "to_object_id": f"DEV_{DEV_POOL_04[dev_idx]}", "object_type": "Device",
         "source_fir_id": fir_id, "observed_date": registered_dt.strftime("%Y-%m-%d"), "confidence": 0.9}
    ]

    txns = [
        {"fir_id": fir_id, "mule_acc_no": acc, "amount": amount // len(used_mule_accs),
         "timestamp": (offence_dt + timedelta(days=1, hours=i)).strftime("%Y-%m-%dT%H:%M")}
        for i, acc in enumerate(used_mule_accs)
    ]

    return fir, victim, mentions, txns


# Baseline "noise" accounts get a plausible-but-not-pool bank, distinct from
# the 7 payments-bank/major-bank names MULE_SET_04 uses so they don't read as
# part of the ring by coincidence.
_BASELINE_BANK_PREFIXES = [
    ("Union Bank of India", "UBIN08"),
    ("Bank of Baroda", "BARB0"),
    ("Indian Bank", "IDIB000"),
    ("Punjab National Bank", "PUNB0"),
]


def _build_baseline_fir(seq: int) -> tuple[FIR, Person, Account, UPI]:
    """
    Baseline task_scam FIR (Tier-B — 'Instagram reel liking' variant).
    INDEPENDENT identifiers — NOT from DEV_POOL_04/MULE_SET_04.
    """
    district = rng.choice(_OTHER_DISTRICTS)
    dist_obj = DISTRICT_MAP[district]
    lat, long = _jitter(dist_obj.lat, dist_obj.long)
    pincode = rng.choice(dist_obj.pincodes)

    offence_dt = _rand_dt(BASELINE_START, BASELINE_END)
    registered_dt = offence_dt + timedelta(days=rng.randint(1, 5))

    fir_id = f"FIR_SCN4_BASE_{seq:02d}"
    victim_id = f"P_{fir_id}_VIC"

    victim = Person(
        person_id=victim_id,
        full_name=_victim_name(),
        age=_victim_age(),
        gender=rng.choice(["Male", "Female"]),
        district=district,
        occupation=_victim_occ(),
        role="victim",
        first_seen_date=registered_dt.strftime("%Y-%m-%d"),
    )

    # Independent identifiers — NOT from pool. These used to be bare strings
    # only referenced from identifiers_mentioned (never wrapped in a real
    # Account/UPI object), so export.py's generic MENTIONS-from-
    # identifiers_mentioned pass (every FIR, not just burst ones) produced a
    # dangling relationship target with no backing row anywhere downstream --
    # confirmed live as the origin of bare {node_id, stub} Neo4j nodes like
    # INDP_ACC_BASE_01_63262. Now real, fully-detailed Account/UPI objects,
    # matching the pool-account construction pattern, just not drawn from
    # identifier_pool.py so they stay outside the shared ring.
    ind_acc = f"INDP_ACC_BASE_{seq:02d}_{rng.randint(10000,99999)}"
    ind_upi = f"baseline.task{seq:02d}@okicici"
    bank_name, ifsc_prefix = rng.choice(_BASELINE_BANK_PREFIXES)
    baseline_account = Account(
        account_no=ind_acc,
        bank=bank_name,
        ifsc=f"{ifsc_prefix}{rng.randint(0, 10**(11 - len(ifsc_prefix)) - 1):0{11 - len(ifsc_prefix)}d}",
        branch_district=district,
        open_date=(offence_dt - timedelta(days=rng.randint(30, 400))).strftime("%Y-%m-%d"),
        kyc_name=f"Task Baseline Mule {seq}",
        is_flagged_mule=True,
    )
    baseline_upi = UPI(upi_id=f"UPI_{ind_upi}", vpa=ind_upi)

    sub_events = [
        SubEvent("Instagram message about reel liking job",  offence_dt.strftime("%Y-%m-%dT%H:%M")),
        SubEvent("first task completed, small payment",      (offence_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("money deposited to unlock premium tasks",  (offence_dt + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("withdrawal refused",                       (offence_dt + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("FIR filed",                                registered_dt.strftime("%Y-%m-%dT%H:%M")),
    ]

    amount = rng.randint(3000, 30000)
    fir = FIR(
        fir_id=fir_id,
        fir_number=f"CR-{100+seq:03d}/2026",
        crime_type="task_scam",
        date_registered=registered_dt.strftime("%Y-%m-%d"),
        date_of_offence=offence_dt.strftime("%Y-%m-%d"),
        district=district,
        pincode=pincode,
        lat=lat,
        long=long,
        police_station=_pick_station(district),
        complainant_person_id=victim_id,
        accused_person_ids=[],
        amount_involved=amount,
        bns_sections=["BNS_318"],
        it_act_sections=["IT_66D"],
        identifiers_mentioned={
            "phones": [],
            "accounts": [ind_acc],
            "upis": [ind_upi],
            "imeis": [],
            "ips": [],
            "wallets": [],
        },
        status="Under Investigation",
        io_officer=rng.choice(IO_OFFICERS),
        narrative_tier="B",  # different sub-script
        sub_events=sub_events,
    )
    return fir, victim, baseline_account, baseline_upi


def _build_pool_objects() -> tuple[list[Device], list[IP], list[Account], list[UPI]]:
    devices = [Device(device_id=f"DEV_{imei}", imei=imei) for imei in DEV_POOL_04]
    ips = [
        IP(
            ip_id=f"IP_{ip_info['ip'].replace('.','_')}",
            ip_address=ip_info["ip"],
            geolocation={"lat": ip_info["lat"], "long": ip_info["long"], "city": ip_info["city"]},
        )
        for ip_info in IP_POOL_04
    ]
    mule_accs = [
        Account(
            account_no=m["account_no"],
            bank=m["bank"],
            ifsc=m["ifsc"],
            branch_district=m["branch_district"],
            open_date="2025-11-01",
            kyc_name=f"Task Ring Mule {i+1}",
            is_flagged_mule=True,
        )
        for i, m in enumerate(MULE_SET_04)
    ]
    mule_upis = [UPI(upi_id=f"UPI_{vpa}", vpa=vpa) for vpa in MULE_UPI_04]
    return devices, ips, mule_accs, mule_upis


def _build_operator_persons() -> list[Person]:
    persons = []
    for i, op in enumerate(SCN4_OPERATORS):
        lo, hi = DEMOGRAPHICS_BY_ROLE["operator"]["age_range"]
        p = Person(
            person_id=f"P_SCN4_OP_{i+1}",
            full_name=op["name"],
            age=rng.randint(lo, hi),
            gender="Male",
            district="Bengaluru Urban",
            occupation=rng.choice(DEMOGRAPHICS_BY_ROLE["operator"]["occupations"]),
            role="operator",
            first_seen_date="2026-04-01",
        )
        persons.append(p)
    return persons


def generate_scenario_4() -> dict:
    """
    Returns burst FIRs, baseline FIRs, pool objects, operator persons.
    Live FIR handled by live_demo_generator.
    """
    firs: list[FIR] = []
    persons: list[Person] = []
    mentions_edges: list[dict] = []
    raw_txns: list[dict] = []

    # Burst FIRs (Tier-A, shared pool identifiers)
    for i in range(1, SCN4_BURST_FIRS + 1):
        fir, victim, mentions, txns = _build_burst_fir(i)
        firs.append(fir)
        persons.append(victim)
        mentions_edges.extend(mentions)
        raw_txns.extend(txns)

    # Baseline FIRs (Tier-B, independent identifiers)
    baseline_accs: list[Account] = []
    baseline_upis: list[UPI] = []
    for i in range(1, SCN4_BASELINE_FIRS + 1):
        fir, victim, baseline_acc, baseline_upi = _build_baseline_fir(i)
        firs.append(fir)
        persons.append(victim)
        baseline_accs.append(baseline_acc)
        baseline_upis.append(baseline_upi)

    # Pool objects
    devices, ips, mule_accs, mule_upis = _build_pool_objects()
    mule_accs = mule_accs + baseline_accs
    mule_upis = mule_upis + baseline_upis

    # Operator persons (revealed by live IR, but their person nodes exist in the historical graph
    # because they appear in the burst FIRs' narrative and USES edges)
    operators = _build_operator_persons()
    persons.extend(operators)

    # Build actual Transaction objects from raw_txns
    transactions = []
    for rt in raw_txns:
        transactions.append(Transaction(
            txn_id=f"TXN_{rt['fir_id']}_M_{rt['mule_acc_no'][-4:]}",
            from_account=f"VICTIM_ACC_{rt['fir_id']}",
            to_account=rt["mule_acc_no"],
            amount=rt["amount"],
            timestamp=rt["timestamp"],
            channel="UPI",
            linked_fir_id=rt["fir_id"],
            hop_role="mule",
            source_fir_id=rt["fir_id"],
        ))

    return {
        "firs": firs,
        "persons": persons,
        "accounts": mule_accs,
        "transactions": transactions,
        "devices": devices,
        "ips": ips,
        "upis": mule_upis,
        "mentions_edges": mentions_edges,
        "_ground_truth": {
            "burst_fir_ids": [f"FIR_SCN4_BURST_{i:02d}" for i in range(1, SCN4_BURST_FIRS + 1)],
            "baseline_fir_ids": [f"FIR_SCN4_BASE_{i:02d}" for i in range(1, SCN4_BASELINE_FIRS + 1)],
            "shared_dev_pool": DEV_POOL_04,
            "shared_ip_pool": [ip["ip"] for ip in IP_POOL_04],
            "shared_mule_set": [m["account_no"] for m in MULE_SET_04],
            "controller_upi": "SCN4_CONTROLLER_UPI — live-only",
            "controller_acc": "SCN4_CONTROLLER_ACC — live-only",
            "operator_persons": [f"P_SCN4_OP_{i+1}" for i in range(len(SCN4_OPERATORS))],
        },
    }
