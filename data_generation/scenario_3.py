"""
scenario_3.py — Follow the Money (Scenario 3)

Plants 2 historical FIRs:
  1. Belagavi digital-arrest FIR — funds route through BRIDGE_ACC_03
  2. A second FIR anchoring HUB_ACC_03 (investment_scam from Dharwad)

Layering ring transactions exist in the historical data (BRIDGE → HUB → mules → WALLET_03).
Live FIR (Dharwad upi_fraud, Sandeep Traders, ₹28L) is handled by live_demo_generator.

Key: connection between the Belagavi case and the new Dharwad case is PURELY STRUCTURAL
(shared BRIDGE_ACC_03). Narratives are unrelated crime types.
"""
from __future__ import annotations
import random
from datetime import datetime, timedelta

from .models import FIR, Person, Account, Transaction, Wallet, SubEvent
from .identifier_pool import (
    BRIDGE_ACC_03, HUB_ACC_03, WALLET_03,
    SCN3_MULE_ACCS, SCN3_FREEZABLE_ACCS
)
from .reference_data import DISTRICT_MAP, STATIONS_BY_DISTRICT, IO_OFFICERS
from .config import RANDOM_SEED, SOUTH_INDIAN_FIRST_NAMES_MALE, SOUTH_INDIAN_LAST_NAMES, DEMOGRAPHICS_BY_ROLE

rng = random.Random(RANDOM_SEED + 3)


def _jitter(lat: float, long: float) -> tuple[float, float]:
    return (
        round(lat + rng.uniform(-0.05, 0.05), 6),
        round(long + rng.uniform(-0.05, 0.05), 6),
    )


def _pick_station(district: str) -> str:
    stations = STATIONS_BY_DISTRICT.get(district, [])
    return rng.choice(stations).station_id if stations else "PS_BLR_CEN_01"


def _build_belagavi_case() -> tuple[FIR, Person, Account, list[Transaction]]:
    """
    Belagavi digital-arrest case. Victim's funds route through BRIDGE_ACC_03.
    This is the historical anchor that 'lights up' when the Dharwad case IR
    mentions the same bridge account.
    """
    district = "Belagavi"
    dist_obj = DISTRICT_MAP[district]
    lat, long = _jitter(dist_obj.lat, dist_obj.long)
    pincode = rng.choice(dist_obj.pincodes)

    offence_dt = datetime(2026, 2, 5, 14, 30, 0)
    registered_dt = offence_dt + timedelta(days=3)

    victim_id = "P_SCN3_H01_VIC"
    victim = Person(
        person_id=victim_id,
        full_name="Siddaraju Hiremath",
        age=58,
        gender="Male",
        address="22, Station Road, Belagavi",
        district=district,
        education="Graduate",
        occupation="Retired Professor",
        employment_status="Retired",
        role="victim",
        first_seen_date=registered_dt.strftime("%Y-%m-%d"),
    )

    bridge_acc = Account(
        account_no=BRIDGE_ACC_03["account_no"],
        bank=BRIDGE_ACC_03["bank"],
        ifsc=BRIDGE_ACC_03["ifsc"],
        branch_district=BRIDGE_ACC_03["branch_district"],
        open_date="2025-08-10",
        kyc_name="Mule Account - Bridge",
        is_flagged_mule=True,
        activity_history=[
            {"timestamp": "2026-02-05T15:00", "direction": "in",  "amount": 1200000},
            {"timestamp": "2026-02-05T15:08", "direction": "out", "amount": 1200000},
        ],
    )

    txns: list[Transaction] = [
        Transaction(
            txn_id="TXN_SCN3_H01_V2B",
            from_account="VICTIM_ACC_SCN3_H01",
            to_account=BRIDGE_ACC_03["account_no"],
            amount=1200000,
            timestamp="2026-02-05T15:00",
            channel="NEFT",
            linked_fir_id="FIR_SCN3_H01",
            hop_role="collection",
            source_fir_id="FIR_SCN3_H01",
        ),
        Transaction(
            txn_id="TXN_SCN3_H01_B2H",
            from_account=BRIDGE_ACC_03["account_no"],
            to_account=HUB_ACC_03["account_no"],
            amount=1200000,
            timestamp="2026-02-05T15:08",
            channel="IMPS",
            linked_fir_id="FIR_SCN3_H01",
            hop_role="aggregation",
            source_fir_id="FIR_SCN3_H01",
        ),
    ]

    sub_events = [
        SubEvent("call from fake CBI officer",         "2026-02-05T14:30"),
        SubEvent("digital arrest via WhatsApp video",  "2026-02-05T14:45"),
        SubEvent("first fund transfer (NEFT)",         "2026-02-05T15:00"),
        SubEvent("fraud realised next morning",        "2026-02-06T09:00"),
        SubEvent("FIR filed",                          registered_dt.strftime("%Y-%m-%dT%H:%M")),
    ]

    fir = FIR(
        fir_id="FIR_SCN3_H01",
        fir_number="CR-019/2026",
        crime_type="digital_arrest",
        date_registered=registered_dt.strftime("%Y-%m-%d"),
        date_of_offence="2026-02-05",
        district=district,
        pincode=pincode,
        lat=lat,
        long=long,
        police_station=_pick_station(district),
        complainant_person_id=victim_id,
        accused_person_ids=[],
        amount_involved=1200000,
        bns_sections=["BNS_318", "BNS_319"],
        it_act_sections=["IT_66C", "IT_66D"],
        identifiers_mentioned={
            "phones": [],
            "accounts": [BRIDGE_ACC_03["account_no"]],
            "upis": [],
            "imeis": [],
            "ips": [],
            "wallets": [],
        },
        status="Under Investigation",
        io_officer=rng.choice(IO_OFFICERS),
        narrative_tier="B",   # different MO from Scn1 ring
        sub_events=sub_events,
    )
    return fir, victim, bridge_acc, txns


def _build_hub_anchor_case() -> tuple[FIR, Person, Account, list[Transaction]]:
    """
    Second historical FIR anchoring HUB_ACC_03.
    An investment_scam case where victim funds route to HUB_ACC_03.
    """
    district = "Dharwad"
    dist_obj = DISTRICT_MAP[district]
    lat, long = _jitter(dist_obj.lat, dist_obj.long)
    pincode = rng.choice(dist_obj.pincodes)

    offence_dt = datetime(2026, 1, 18, 11, 0, 0)
    registered_dt = offence_dt + timedelta(days=5)

    victim_id = "P_SCN3_H02_VIC"
    victim = Person(
        person_id=victim_id,
        full_name="Kavitha Desai",
        age=38,
        gender="Female",
        address="45, Hubli Road, Dharwad",
        district=district,
        education="Post Graduate",
        occupation="IT Professional",
        employment_status="Employed",
        role="victim",
        first_seen_date=registered_dt.strftime("%Y-%m-%d"),
    )

    hub_acc = Account(
        account_no=HUB_ACC_03["account_no"],
        bank=HUB_ACC_03["bank"],
        ifsc=HUB_ACC_03["ifsc"],
        branch_district=HUB_ACC_03["branch_district"],
        open_date="2025-06-01",
        kyc_name=HUB_ACC_03["kyc_name"],
        is_flagged_mule=True,
        activity_history=[
            {"timestamp": "2026-01-18T11:30", "direction": "in", "amount": 500000},
            {"timestamp": "2026-02-05T15:10", "direction": "in", "amount": 1200000},  # from bridge
        ],
    )

    txns: list[Transaction] = [
        Transaction(
            txn_id="TXN_SCN3_H02_V2H",
            from_account="VICTIM_ACC_SCN3_H02",
            to_account=HUB_ACC_03["account_no"],
            amount=500000,
            timestamp="2026-01-18T11:30",
            channel="UPI",
            linked_fir_id="FIR_SCN3_H02",
            hop_role="collection",
            source_fir_id="FIR_SCN3_H02",
        )
    ]

    sub_events = [
        SubEvent("WhatsApp investment group invite",  "2026-01-10T09:00"),
        SubEvent("initial test withdrawal of ₹5K",   "2026-01-12T10:00"),
        SubEvent("₹5L investment transferred",        "2026-01-18T11:30"),
        SubEvent("withdrawal blocked, contact lost",  "2026-01-22T14:00"),
        SubEvent("FIR filed",                         registered_dt.strftime("%Y-%m-%dT%H:%M")),
    ]

    fir = FIR(
        fir_id="FIR_SCN3_H02",
        fir_number="CR-009/2026",
        crime_type="investment_scam",
        date_registered=registered_dt.strftime("%Y-%m-%d"),
        date_of_offence="2026-01-18",
        district=district,
        pincode=pincode,
        lat=lat,
        long=long,
        police_station=_pick_station(district),
        complainant_person_id=victim_id,
        accused_person_ids=[],
        amount_involved=500000,
        bns_sections=["BNS_318"],
        it_act_sections=["IT_66C"],
        identifiers_mentioned={
            "phones": [],
            "accounts": [HUB_ACC_03["account_no"]],
            "upis": [],
            "imeis": [],
            "ips": [],
            "wallets": [],
        },
        status="Under Investigation",
        io_officer=rng.choice(IO_OFFICERS),
        narrative_tier="C",
        sub_events=sub_events,
    )
    return fir, victim, hub_acc, txns


# Collector (aggregation-feeder) accounts: many accounts pour into HUB_ACC_03, making it
# the highest in-degree / highest-volume node so "rank the busiest aggregation account"
# (PageRank/degree, Scn3 Q3) surfaces the hub. Amounts ~₹16L; with the ₹12L bridge inflow
# the hub aggregates ~₹28L (the victim's loss).
_SCN3_COLLECTORS = [
    {"account_no": "5530123456789031", "bank": "Canara Bank",         "ifsc": "CNRB0009031", "branch_district": "Dharwad",          "amount": 280000},
    {"account_no": "5530123456789032", "bank": "State Bank of India", "ifsc": "SBIN0009032", "branch_district": "Hubballi-Dharwad", "amount": 260000},
    {"account_no": "5530123456789033", "bank": "Bank of Baroda",      "ifsc": "BARB0DHARW3", "branch_district": "Dharwad",          "amount": 250000},
    {"account_no": "5530123456789034", "bank": "Union Bank of India", "ifsc": "UBIN0553434", "branch_district": "Belagavi",         "amount": 240000},
    {"account_no": "5530123456789035", "bank": "Karnataka Bank",      "ifsc": "KTKM0009035", "branch_district": "Vijayapura",       "amount": 230000},
    {"account_no": "5530123456789036", "bank": "ICICI Bank",          "ifsc": "ICIC0009036", "branch_district": "Bengaluru Urban",  "amount": 340000},
]

# HUB → mule sub-₹1L tranches. The two freezable mules (…013, …014) receive several tranches
# and never move them on, accumulating ≈₹6.2L still recoverable; the rest cash out to crypto.
# Index aligns with SCN3_MULE_ACCS; …013/…014 are indexes 2/3 (== SCN3_FREEZABLE_ACCS).
_SCN3_MULE_PLAN = [
    {"tranches": [90000, 90000, 90000, 90000], "cash_out": True},   # …011 -> crypto  ₹3.6L
    {"tranches": [90000, 90000, 90000, 90000], "cash_out": True},   # …012 -> crypto  ₹3.6L
    {"tranches": [90000, 85000, 80000, 65000], "cash_out": False},  # …013 FROZEN     ₹3.2L
    {"tranches": [85000, 80000, 75000, 60000], "cash_out": False},  # …014 FROZEN     ₹3.0L
    {"tranches": [90000, 90000, 90000, 90000], "cash_out": True},   # …015 -> crypto  ₹3.6L
]


def _build_mule_accounts() -> tuple[list[Account], list[Transaction]]:
    """
    Aggregation feeders + layering ring around HUB_ACC_03.
      collectors → HUB (aggregation, high in-degree)  →  mules (sub-₹1L tranches)  →  crypto,
      with two freezable mules holding ≈₹6.2L that never moved on.
    """
    mule_accs: list[Account] = []
    txns: list[Transaction] = []
    hub = HUB_ACC_03["account_no"]

    # --- Aggregation layer: victim → collector → HUB (drives hub centrality) ---
    agg_base = datetime(2026, 2, 5, 15, 2, 0)
    for i, col in enumerate(_SCN3_COLLECTORS):
        t_in = agg_base + timedelta(minutes=i * 2)
        t_out = t_in + timedelta(minutes=1)
        mule_accs.append(Account(
            account_no=col["account_no"], bank=col["bank"], ifsc=col["ifsc"],
            branch_district=col["branch_district"],
            open_date=(datetime(2024, 1, 1) + timedelta(days=rng.randint(0, 365))).strftime("%Y-%m-%d"),
            kyc_name=f"Collector {i+1}", is_flagged_mule=True,
            activity_history=[
                {"timestamp": t_in.strftime("%Y-%m-%dT%H:%M"),  "direction": "in",  "amount": col["amount"]},
                {"timestamp": t_out.strftime("%Y-%m-%dT%H:%M"), "direction": "out", "amount": col["amount"]},
            ],
        ))
        txns.append(Transaction(
            txn_id=f"TXN_SCN3_AGG_V2C_{i+1}", from_account="VICTIM_ACC_SCN3_LIVE",
            to_account=col["account_no"], amount=col["amount"], timestamp=t_in.strftime("%Y-%m-%dT%H:%M"),
            channel="IMPS", linked_fir_id="FIR_SCN3_LIVE", hop_role="collection", source_fir_id="FIR_SCN3_H01",
        ))
        txns.append(Transaction(
            txn_id=f"TXN_SCN3_AGG_C2H_{i+1}", from_account=col["account_no"],
            to_account=hub, amount=col["amount"], timestamp=t_out.strftime("%Y-%m-%dT%H:%M"),
            channel="IMPS", linked_fir_id="FIR_SCN3_LIVE", hop_role="aggregation", source_fir_id="FIR_SCN3_H01",
        ))

    # --- Layering: HUB → mules in sub-₹1L tranches; freezable mules retain funds ---
    layer_base = datetime(2026, 2, 5, 15, 15, 0)
    t = layer_base
    for idx, mule_raw in enumerate(SCN3_MULE_ACCS):
        plan = _SCN3_MULE_PLAN[idx]
        history: list[dict] = []
        for j, amt in enumerate(plan["tranches"]):
            history.append({"timestamp": t.strftime("%Y-%m-%dT%H:%M"), "direction": "in", "amount": amt})
            txns.append(Transaction(
                txn_id=f"TXN_SCN3_LAYER_H2M_{idx+1}_{j+1}", from_account=hub,
                to_account=mule_raw["account_no"], amount=amt, timestamp=t.strftime("%Y-%m-%dT%H:%M"),
                channel="IMPS", linked_fir_id="FIR_SCN3_LIVE", hop_role="mule", source_fir_id="FIR_SCN3_H01",
            ))
            t += timedelta(minutes=1)
            if plan["cash_out"]:
                history.append({"timestamp": t.strftime("%Y-%m-%dT%H:%M"), "direction": "out", "amount": amt})
                txns.append(Transaction(
                    txn_id=f"TXN_SCN3_LAYER_M2W_{idx+1}_{j+1}", from_account=mule_raw["account_no"],
                    to_account=WALLET_03["address"], amount=amt, timestamp=t.strftime("%Y-%m-%dT%H:%M"),
                    channel="crypto", linked_fir_id="FIR_SCN3_LIVE", hop_role="cash_out", source_fir_id="FIR_SCN3_H01",
                ))
                t += timedelta(minutes=1)
        mule_accs.append(Account(
            account_no=mule_raw["account_no"], bank=mule_raw["bank"], ifsc=mule_raw["ifsc"],
            branch_district=mule_raw["branch_district"],
            open_date=(datetime(2024, 1, 1) + timedelta(days=rng.randint(0, 365))).strftime("%Y-%m-%d"),
            kyc_name=f"Mule {idx+1}", is_flagged_mule=True, activity_history=history,
        ))

    return mule_accs, txns


def _build_wallet() -> Wallet:
    from .models import Wallet as W
    return W(wallet_id=f"WALLET_{WALLET_03['address'][:8]}", address=WALLET_03["address"], chain=WALLET_03["chain"])


def generate_scenario_3() -> dict:
    """
    Returns historical data only. Live FIR handled by live_demo_generator.
    """
    firs: list[FIR] = []
    persons: list[Person] = []
    accounts: list[Account] = []
    transactions: list[Transaction] = []

    # Case 1: Belagavi digital-arrest (contains BRIDGE_ACC_03)
    fir1, vic1, bridge_acc, txns1 = _build_belagavi_case()
    firs.append(fir1)
    persons.append(vic1)
    accounts.append(bridge_acc)
    transactions.extend(txns1)

    # Case 2: Dharwad investment_scam (anchors HUB_ACC_03)
    fir2, vic2, hub_acc, txns2 = _build_hub_anchor_case()
    firs.append(fir2)
    persons.append(vic2)
    accounts.append(hub_acc)
    transactions.extend(txns2)

    # Layering ring (mule accounts + transactions)
    mule_accs, layer_txns = _build_mule_accounts()
    accounts.extend(mule_accs)
    transactions.extend(layer_txns)

    wallet = _build_wallet()

    return {
        "firs": firs,
        "persons": persons,
        "accounts": accounts,
        "transactions": transactions,
        "wallets": [wallet],
        "_ground_truth": {
            "bridge_fir_ids": ["FIR_SCN3_H01", "FIR_SCN3_LIVE"],
            "bridge_acc": BRIDGE_ACC_03["account_no"],
            "hub_acc": HUB_ACC_03["account_no"],
            "hub_operator": HUB_ACC_03["kyc_name"],
            "wallet": WALLET_03["address"],
            "freezable_accs": SCN3_FREEZABLE_ACCS,
            "freezable_amount": 620000,   # …013 ₹3.2L + …014 ₹3.0L
        },
    }
