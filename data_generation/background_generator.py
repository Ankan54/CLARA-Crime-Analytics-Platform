"""
background_generator.py — 34 noise FIRs with independent identifiers.

Distribution from config.py BACKGROUND_CRIME_TYPE_DISTRIBUTION.
Bengaluru-weighted (~40% of cases).
Role-conditioned demographics.
NO pooled identifiers from identifier_pool.py — enforced by validation.
Investigation reports: ~26 historical (one per FIR approx).
"""
from __future__ import annotations
import uuid
import random
from datetime import datetime, timedelta

from .models import FIR, Person, Account, Transaction, InvestigationReport, SubEvent
from .reference_data import DISTRICT_MAP, DISTRICTS, STATIONS_BY_DISTRICT, IO_OFFICERS, BANKS
from .config import (
    RANDOM_SEED, DEMO_DATE_STR,
    BACKGROUND_CRIME_TYPE_DISTRIBUTION, BENGALURU_WEIGHT,
    SOUTH_INDIAN_FIRST_NAMES_MALE, SOUTH_INDIAN_FIRST_NAMES_FEMALE,
    SOUTH_INDIAN_LAST_NAMES, DEMOGRAPHICS_BY_ROLE,
    HISTORICAL_WINDOW_MONTHS,
)
from .identifier_pool import ALL_POOL_IDENTIFIERS

rng = random.Random(RANDOM_SEED + 99)

DEMO_DT = datetime.strptime(DEMO_DATE_STR, "%Y-%m-%d")
HIST_START = DEMO_DT - timedelta(days=HISTORICAL_WINDOW_MONTHS * 30)

# Districts excluding scenario-anchored ones (to avoid confusion in data)
_ALL_DISTRICTS = [d.name for d in DISTRICTS]
_BENGALURU_DISTRICTS = ["Bengaluru Urban", "Bengaluru Rural"]
_OTHER_DISTRICTS = [d for d in _ALL_DISTRICTS if d not in ("Mysuru", "Mangaluru", "Hubballi-Dharwad",
                                                              "Belagavi", "Dharwad", "Tumakuru",
                                                              "Bengaluru Urban", "Bengaluru Rural")]


def _pick_district() -> str:
    """~40% Bengaluru, remainder spread across other Karnataka districts."""
    if rng.random() < BENGALURU_WEIGHT:
        return rng.choice(_BENGALURU_DISTRICTS)
    return rng.choice(_OTHER_DISTRICTS)


def _pick_station(district: str) -> str:
    stations = STATIONS_BY_DISTRICT.get(district, [])
    return rng.choice(stations).station_id if stations else "PS_BLR_CEN_01"


def _male_name() -> str:
    return f"{rng.choice(SOUTH_INDIAN_FIRST_NAMES_MALE)} {rng.choice(SOUTH_INDIAN_LAST_NAMES)}"


def _female_name() -> str:
    return f"{rng.choice(SOUTH_INDIAN_FIRST_NAMES_FEMALE)} {rng.choice(SOUTH_INDIAN_LAST_NAMES)}"


def _any_name(gender: str) -> str:
    return _male_name() if gender == "Male" else _female_name()


def _jitter(lat: float, long: float) -> tuple[float, float]:
    return (
        round(lat + rng.uniform(-0.05, 0.05), 6),
        round(long + rng.uniform(-0.05, 0.05), 6),
    )


def _rand_dt(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(seconds=rng.randint(0, max(1, int(delta.total_seconds()))))


def _make_ifsc(bank_code: str, district_code: str) -> str:
    """Generate valid IFSC: 4 letters + 0 + 6 alphanumeric."""
    suffix = "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
    return f"{bank_code}0{suffix}"


def _make_account_no() -> str:
    return f"BG{rng.randint(10000000000, 99999999999):011d}"


def _make_phone() -> str:
    return f"9{rng.randint(100000000, 999999999)}"


def _make_upi(name: str) -> str:
    tag = name.replace(" ", "").lower()[:8]
    return f"{tag}{rng.randint(10,99)}@okicici"


def _make_imei() -> str:
    return "".join([str(rng.randint(0, 9)) for _ in range(15)])


def _ensure_no_pool_contamination(identifiers: list[str]) -> list[str]:
    """
    Safety net: replace any accidentally-generated identifier that matches a pool value.
    (Should never trigger if generation logic is correct, but protects against collisions.)
    """
    clean = []
    for idf in identifiers:
        if idf in ALL_POOL_IDENTIFIERS:
            # Regenerate
            clean.append(f"SAFE_{rng.randint(100000000, 999999999)}")
        else:
            clean.append(idf)
    return clean


# ---------------------------------------------------------------------------
# Crime-type specific builders
# ---------------------------------------------------------------------------

def _build_digital_arrest_bg(fir_id: str, seq: int, district: str,
                               offence_dt: datetime) -> tuple[FIR, Person, Account, list[Transaction], list[SubEvent]]:
    dem = DEMOGRAPHICS_BY_ROLE["victim_digital_arrest"]
    gender = rng.choice(dem["gender"])
    victim_name = _any_name(gender)
    victim_age = rng.randint(*dem["age_range"])
    occ = rng.choice(dem["occupations"])

    victim_id = f"P_{fir_id}_VIC"
    victim = Person(
        person_id=victim_id, full_name=victim_name, age=victim_age, gender=gender,
        district=district, occupation=occ, role="victim",
        first_seen_date=(offence_dt + timedelta(days=2)).strftime("%Y-%m-%d"),
    )

    acc_no = _make_account_no()
    bank = rng.choice(BANKS)
    dist_obj = DISTRICT_MAP.get(district, DISTRICT_MAP["Bengaluru Urban"])
    acc = Account(
        account_no=acc_no, bank=bank.name,
        ifsc=_make_ifsc(bank.ifsc_prefix, district[:3].upper()),
        branch_district=district, open_date="2024-01-01", kyc_name="BG Mule",
        is_flagged_mule=True,
    )

    amount = rng.randint(200000, 3000000)
    txn = Transaction(
        txn_id=f"TXN_{fir_id}_V2M",
        from_account=f"VICTIM_ACC_{fir_id}", to_account=acc_no,
        amount=amount, timestamp=offence_dt.strftime("%Y-%m-%dT%H:%M"),
        channel="NEFT", linked_fir_id=fir_id, hop_role="collection", source_fir_id=fir_id,
    )

    sub_events = [
        SubEvent("call from fake official",            offence_dt.strftime("%Y-%m-%dT%H:%M")),
        SubEvent("digital arrest threat",              (offence_dt + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("fund transfer",                      (offence_dt + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M")),
        SubEvent("FIR filed",                          (offence_dt + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")),
    ]
    # Tier B (NCB/customs variant)
    return victim, acc, [txn], sub_events, victim_id, amount, acc_no


def _build_generic_bg(fir_id: str, crime_type: str, district: str, offence_dt: datetime) -> tuple:
    """Generic background case for all other crime types."""
    role_key_map = {
        "investment_scam": "victim_investment_scam",
        "upi_fraud": "victim_upi_fraud",
        "task_scam": "victim_task_scam",
        "loan_app": "victim_task_scam",
        "otp_fraud": "victim_investment_scam",
        "job_scam": "victim_task_scam",
        "sextortion": "victim_investment_scam",
        "phishing": "victim_investment_scam",
        "mule_account": "mule",
    }
    dem_key = role_key_map.get(crime_type, "victim_investment_scam")
    dem = DEMOGRAPHICS_BY_ROLE[dem_key]
    gender = rng.choice(dem["gender"])
    victim_name = _any_name(gender)
    victim_age = rng.randint(*dem["age_range"])
    occ = rng.choice(dem["occupations"])

    victim_id = f"P_{fir_id}_VIC"
    victim = Person(
        person_id=victim_id, full_name=victim_name, age=victim_age, gender=gender,
        district=district, occupation=occ, role="victim",
        first_seen_date=(offence_dt + timedelta(days=2)).strftime("%Y-%m-%d"),
    )

    acc_no = _make_account_no()
    bank = rng.choice(BANKS)
    acc = Account(
        account_no=acc_no, bank=bank.name,
        ifsc=_make_ifsc(bank.ifsc_prefix, district[:3].upper()),
        branch_district=district, open_date="2024-06-01", kyc_name="BG Account",
        is_flagged_mule=crime_type in ("mule_account",),
    )

    amount = rng.randint(5000, 500000)
    phone = _make_phone()
    upi = _make_upi(victim_name)

    sub_events_by_type = {
        "investment_scam": [
            SubEvent("investment offer on WhatsApp",       offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("test withdrawal succeeded",          (offence_dt + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("large investment transferred",       (offence_dt + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("withdrawal blocked",                 (offence_dt + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                          (offence_dt + timedelta(days=12)).strftime("%Y-%m-%dT%H:%M")),
        ],
        "upi_fraud": [
            SubEvent("fake UPI request sent",              offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("payment made under confusion",        (offence_dt + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                          (offence_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")),
        ],
        "task_scam": [
            SubEvent("task group invite",                  offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("first deposit to unlock tasks",      (offence_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("withdrawal refused",                 (offence_dt + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                          (offence_dt + timedelta(days=6)).strftime("%Y-%m-%dT%H:%M")),
        ],
        "loan_app": [
            SubEvent("loan app installed",                 offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("personal data harvested",            (offence_dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("harassment calls started",           (offence_dt + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                          (offence_dt + timedelta(days=20)).strftime("%Y-%m-%dT%H:%M")),
        ],
        "otp_fraud": [
            SubEvent("fake bank call received",            offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("OTP shared",                         (offence_dt + timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("account drained",                    (offence_dt + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                          (offence_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")),
        ],
        "job_scam": [
            SubEvent("fake job offer received",            offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("registration fee paid",              (offence_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("offer turned out fake",              (offence_dt + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                          (offence_dt + timedelta(days=11)).strftime("%Y-%m-%dT%H:%M")),
        ],
        "sextortion": [
            SubEvent("befriended on social media",         offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("compromising call recorded",         (offence_dt + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("blackmail demand received",          (offence_dt + timedelta(days=6)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                          (offence_dt + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M")),
        ],
        "phishing": [
            SubEvent("fake bank SMS received",             offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("credentials entered on fake site",   (offence_dt + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("account accessed by fraudster",      (offence_dt + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed",                          (offence_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")),
        ],
        "mule_account": [
            SubEvent("recruited to share bank account",    offence_dt.strftime("%Y-%m-%dT%H:%M")),
            SubEvent("account used for illegal transfers", (offence_dt + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("account frozen",                     (offence_dt + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M")),
            SubEvent("FIR filed against account holder",   (offence_dt + timedelta(days=35)).strftime("%Y-%m-%dT%H:%M")),
        ],
    }
    sub_events = sub_events_by_type.get(crime_type, sub_events_by_type["upi_fraud"])

    bns_by_type = {
        "digital_arrest": ["BNS_318", "BNS_319"],
        "investment_scam": ["BNS_318"],
        "task_scam": ["BNS_318"],
        "upi_fraud": ["BNS_318", "BNS_319"],
        "loan_app": ["BNS_318"],
        "otp_fraud": ["BNS_319"],
        "job_scam": ["BNS_318"],
        "sextortion": ["BNS_318", "BNS_319"],
        "phishing": ["BNS_319"],
        "mule_account": ["PMLA_3"],
    }

    return victim, acc, amount, phone, upi, sub_events, victim_id, bns_by_type.get(crime_type, ["BNS_318"])


def _build_fir(fir_id: str, fir_number: str, crime_type: str, district: str,
               offence_dt: datetime, victim_id: str, amount: int,
               acc_no: str, phone: str, upi: str,
               sub_events: list[SubEvent], io: str, bns_sections: list[str]) -> FIR:
    dist_obj = DISTRICT_MAP.get(district, DISTRICT_MAP["Bengaluru Urban"])
    lat, long = _jitter(dist_obj.lat, dist_obj.long)
    pincode = rng.choice(dist_obj.pincodes)
    registered_dt = offence_dt + timedelta(days=rng.randint(1, 7))

    clean_acc = _ensure_no_pool_contamination([acc_no])[0]
    clean_phone = _ensure_no_pool_contamination([phone])[0]
    clean_upi = _ensure_no_pool_contamination([upi])[0]

    tier_map = {
        "digital_arrest": "B",
        "investment_scam": "C",
        "task_scam": "B",
        "upi_fraud": "C",
        "loan_app": "C",
        "otp_fraud": "C",
        "job_scam": "C",
        "sextortion": "C",
        "phishing": "C",
        "mule_account": "C",
    }

    return FIR(
        fir_id=fir_id,
        fir_number=fir_number,
        crime_type=crime_type,
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
        bns_sections=bns_sections,
        it_act_sections=["IT_66C"] if crime_type not in ("mule_account",) else [],
        identifiers_mentioned={
            "phones": [clean_phone] if phone else [],
            "accounts": [clean_acc],
            "upis": [clean_upi] if upi else [],
            "imeis": [],
            "ips": [],
            "wallets": [],
        },
        status="Under Investigation",
        io_officer=io,
        narrative_tier=tier_map.get(crime_type, "C"),
        sub_events=sub_events,
    )


def generate_background(start_seq: int = 300) -> dict:
    """
    Generate 34 background FIRs + persons + accounts + IRs.
    start_seq: fir_number sequence start (avoid collision with scenario FIR numbers).
    """
    firs: list[FIR] = []
    persons: list[Person] = []
    accounts: list[Account] = []
    transactions: list[Transaction] = []
    investigation_reports: list[InvestigationReport] = []

    # Expand crime type distribution into a flat list
    crime_type_list: list[str] = []
    for ct, count in BACKGROUND_CRIME_TYPE_DISTRIBUTION.items():
        crime_type_list.extend([ct] * count)
    rng.shuffle(crime_type_list)

    for i, crime_type in enumerate(crime_type_list):
        seq = start_seq + i
        fir_id = f"FIR_BG_{seq:03d}"
        fir_number = f"CR-{seq:03d}/2026"
        district = _pick_district()
        offence_dt = _rand_dt(HIST_START, DEMO_DT - timedelta(days=30))
        io = rng.choice(IO_OFFICERS)

        if crime_type == "digital_arrest":
            victim, acc, txns, sub_events, victim_id, amount, acc_no = _build_digital_arrest_bg(
                fir_id, seq, district, offence_dt
            )
            phone = _make_phone()
            upi = ""
        else:
            victim, acc, amount, phone, upi, sub_events, victim_id, bns_sections = _build_generic_bg(
                fir_id, crime_type, district, offence_dt
            )
            acc_no = acc.account_no
            txns = [Transaction(
                txn_id=f"TXN_{fir_id}_V2M",
                from_account=f"VICTIM_ACC_{fir_id}",
                to_account=acc_no,
                amount=amount,
                timestamp=offence_dt.strftime("%Y-%m-%dT%H:%M"),
                channel=rng.choice(["UPI", "IMPS"]),
                linked_fir_id=fir_id,
                hop_role="collection",
                source_fir_id=fir_id,
            )]

        if crime_type == "digital_arrest":
            bns_sections = ["BNS_318", "BNS_319"]

        fir = _build_fir(
            fir_id=fir_id, fir_number=fir_number, crime_type=crime_type,
            district=district, offence_dt=offence_dt,
            victim_id=victim_id, amount=amount,
            acc_no=acc_no, phone=phone, upi=upi,
            sub_events=sub_events, io=io, bns_sections=bns_sections,
        )
        firs.append(fir)
        persons.append(victim)
        accounts.append(acc)
        transactions.extend(txns if isinstance(txns, list) else [txns])

        # ~80% of background FIRs get an investigation report
        if rng.random() < 0.80:
            ir_date = offence_dt + timedelta(days=rng.randint(7, 30))
            ir = InvestigationReport(
                report_id=f"IR_BG_{seq:03d}",
                fir_id=fir_id,
                report_date=ir_date.strftime("%Y-%m-%d"),
                io_officer=io,
                newly_linked_identifiers={},
                linked_fir_ids=[],
                seized_items=[],
                arrests=[],
                money_trail_notes=f"Victim transferred ₹{amount:,} via {rng.choice(['UPI','NEFT','IMPS'])}. Account {acc_no} flagged as mule.",
                suspected_roles=[{"person_id": victim_id, "role": "victim"}],
            )
            investigation_reports.append(ir)

    return {
        "firs": firs,
        "persons": persons,
        "accounts": accounts,
        "transactions": transactions,
        "investigation_reports": investigation_reports,
    }
