"""
live_demo_generator.py - Generate 4 held-back live demo documents.

Each scenario emits under output/live_demo/scenario_{n}/:
  fir.txt                   - English FIR with realistic header block
  fir.kn.txt                - Kannada translation (via Bedrock)
  fir.kn_backtranslation.txt - English back-translation for verification
  investigation_report.txt  - IR revealing live-only identifiers
  fir.expected.json         - Ground-truth extraction target for ingestion pipeline
  ir.expected.json          - Ground-truth target for IR ingestion

CONTRACT:
- FIR header block contains exactly: Police Station, District, CrimeNo, CaseNo,
  Date of Registration, Date/Time of Offence, Complainant (name/age/occupation),
  Accused, Sections
- Extension identifiers are SAME LITERAL POOL VALUES as historical data -> link forms on ingest
- Live Accused have own AccusedMasterID; NO RESOLVED_AS/LINKED_TO edges pre-baked
- Live-only identifiers (CTRL_UPI_01, CTRL_IMEI_01) appear ONLY here, never in historical data
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config
from . import id_registry as reg
from . import ksp_master as km
from .identifier_pool import (
    AGG_ACC_01, CTRL_IMEI_01, CTRL_UPI_01, SCN1_MULE_KYC_NAME,
    DEV_IMEI_02, UPI_02, PHONE_02,
    BRIDGE_ACC_03, HUB_ACC_03, SCN3_FREEZABLE_ACCS,
    DEV_POOL_04, IP_POOL_04, MULE_SET_04,
    SCN4_CONTROLLER_UPI, SCN4_CONTROLLER_ACC, SCN4_OPERATORS,
)
from .legal_layer import sections_label_list, sections_for_crime_type
from .narrative_generator import NarrativeGenerator, build_tier_a_digital_arrest_prompt

# ---------------------------------------------------------------------------
# FIR header block template
# ---------------------------------------------------------------------------
FIR_HEADER_TEMPLATE = """FIRST INFORMATION REPORT
Police Station: {station_name}   District: {district_name}
Crime No: {crime_no}   Case No: {case_no}
Date of Registration: {reg_date}   Date/Time of Offence: {offence_from} to {offence_to}
Complainant: {complainant_name}, Age {complainant_age}, Occupation: {complainant_occupation}
Accused: {accused_names}
Sections: {sections}
---
"""

def build_fir_header(station_id: str, crime_no: str, case_no: str,
                     reg_date: str, offence_from: str, offence_to: str,
                     complainant_name: str, complainant_age: int,
                     complainant_occupation: str,
                     accused_names: List[str], crime_type: str) -> str:
    unit_id = km.STATION_ID_TO_UNIT_ID.get(station_id, 1001)
    unit = km.UNIT_MAP[unit_id]
    district = km.DISTRICT_BY_ID[unit.district_id]
    station_unit = unit.unit_name
    section_str = sections_label_list(crime_type)
    return FIR_HEADER_TEMPLATE.format(
        station_name      = station_unit,
        district_name     = district.district_name,
        crime_no          = crime_no,
        case_no           = case_no,
        reg_date          = reg_date,
        offence_from      = offence_from,
        offence_to        = offence_to,
        complainant_name  = complainant_name,
        complainant_age   = complainant_age,
        complainant_occupation = complainant_occupation,
        accused_names     = ", ".join(accused_names) if accused_names else "Unknown / Under Investigation",
        sections          = section_str,
    )

# ---------------------------------------------------------------------------
# Expected JSON builder
# ---------------------------------------------------------------------------

def build_fir_expected(
    scenario_key: str,
    crime_no: str,
    case_no: str,
    station_id: str,
    crime_type: str,
    complainant: Dict,
    accused_list: List[Dict],
    revealed_identifiers: Dict[str, List[str]],
    connects_to: List[Dict],
    reg_date: str = "2026-06-26",
    extension_rows: Optional[Dict] = None,
) -> Dict:
    """
    Build the fir.expected.json ground-truth dict.
    extension_rows is the FULL extraction target for the ingestion pipeline:
    {
      "accounts":      [{"AccountNo": ..., "Bank": ..., "IFSC": ..., ...}],
      "devices":       [{"IMEI": ..., ...}],
      "upis":          [{"VPA": ..., ...}],
      "phones":        [{"Number": ..., ...}],
      "ips":           [{"IPAddress": ..., ...}],
      "wallets":       [{"Address": ..., "Chain": ..., ...}],
      "transactions":  [{"FromAccount":..., "ToAccount":..., "Amount":..., "source_caseid":..., "confidence":...}],
      "rels_uses":     [{"from_person_id":..., "to_object_id":..., "source_caseid":..., "confidence":...}],
    }
    Identifiers in extension_rows MUST byte-match historical dimension rows.
    """
    unit_id = km.STATION_ID_TO_UNIT_ID[station_id]
    district_id = km.UNIT_MAP[unit_id].district_id
    district_name = km.DISTRICT_BY_ID[district_id].district_name
    category_id = config.CASE_CATEGORY_FIR
    status_id = km.CASE_STATUS_MAP.get("Under Investigation", 1)
    major_head = km.CRIME_TYPE_TO_HEAD_ID.get(crime_type, 101)
    minor_head = km.CRIME_TYPE_TO_SUB_HEAD_ID.get(crime_type, 1011)
    charged_sections = [
        {"act_code": a, "section_code": s}
        for a, s in sections_for_crime_type(crime_type)
    ]
    result = {
        "scenario_key":     scenario_key,
        "CrimeNo":          crime_no,
        "CaseNo":           case_no,
        "PoliceStationID":  unit_id,
        "PoliceStationName":km.UNIT_MAP[unit_id].unit_name,
        "DistrictID":       district_id,
        "DistrictName":     district_name,
        "CaseCategoryID":   category_id,
        "CaseStatusID":     status_id,
        "CrimeMajorHeadID": major_head,
        "CrimeMinorHeadID": minor_head,
        "CrimeRegisteredDate": reg_date,
        "complainant":      complainant,
        "accused":          accused_list,
        "charged_sections": charged_sections,
        "revealed_identifiers": revealed_identifiers,
        "connects_to":      connects_to,
        "extension_extraction_target": extension_rows or {},
        "_note": "Live Accused rows have own AccusedMasterIDs. No RESOLVED_AS/LINKED_TO pre-baked."
    }
    return result

def build_ir_expected(
    scenario_key: str,
    crime_no: str,
    newly_revealed: Dict[str, List[str]],
    money_trail_summary: str,
    connects_to: List[Dict],
    extension_rows: Optional[Dict] = None,
) -> Dict:
    """Build the ir.expected.json ground-truth dict with full extension extraction target."""
    return {
        "scenario_key":          scenario_key,
        "CrimeNo":               crime_no,
        "newly_revealed_identifiers": newly_revealed,
        "money_trail_summary":   money_trail_summary,
        "connects_to":           connects_to,
        "extension_extraction_target": extension_rows or {},
        "_note": "Live IR reveals identifiers not present in historical data.",
    }

# ---------------------------------------------------------------------------
# Scenario 1 live doc — Digital Arrest Ring reveal
# ---------------------------------------------------------------------------

def generate_scn1_live(gen: NarrativeGenerator, base: Path,
                       historical_crime_nos: List[str]) -> None:
    res = reg.get_live_reservation("LIVE_SCN1")
    crime_no = res["crime_no"]
    case_no  = res["case_no"]
    station_id = res["station_id"]
    reg_date = "2026-06-26"
    crime_type = "digital_arrest"

    complainant = {"name": "Dr. Anand Rao", "age": 58, "occupation": "Retired Professor",
                   "gender": "M"}
    accused_logical_id = "P_SCN1_LIVE_A1"
    accused_master_id = reg.accused_master_id(accused_logical_id)
    accused = [{"person_id_label": "A1", "name": SCN1_MULE_KYC_NAME,
                "AccusedMasterID": accused_master_id,
                "age": 28, "gender": "M", "occupation": "Unemployed",
                "is_arrested": True,
                "_note": "Own AccusedMasterID; un-merged from any historical alias"}]

    revealed = {
        "accounts": [AGG_ACC_01["account_no"]],
        "imeis":    [CTRL_IMEI_01],
        "upis":     [CTRL_UPI_01],
        "phones":   [],
        "ips":      [],
    }
    connects_to = [
        {"historical_case_crime_no": cn,
         "via_identifier": AGG_ACC_01["account_no"],
         "identifier_type": "account_no",
         "_note": "Aggregation account AGG_ACC_01 is the shared link"}
        for cn in historical_crime_nos
    ]

    header = build_fir_header(
        station_id, crime_no, case_no,
        reg_date, "2026-06-26T10:15:00", "2026-06-26T14:30:00",
        complainant["name"], complainant["age"], complainant["occupation"],
        [SCN1_MULE_KYC_NAME], crime_type
    )

    # Use the SAME tier-A digital-arrest template as the 3 historical scn1 cases so the
    # live FIR is near-duplicate to them by MEANING (the "same script across districts" wow).
    # The controller IMEI/UPI are NOT in the FIR (the victim can't know them) — they are
    # revealed in the investigation report below.
    _station_unit = km.UNIT_MAP[km.STATION_ID_TO_UNIT_ID.get(station_id, 1001)]
    prompt = build_tier_a_digital_arrest_prompt(
        victim_name=complainant["name"], age=complainant["age"],
        address="Malleswaram, Bengaluru", district="Bengaluru Urban",
        date=reg_date, time="10:15", hours=24, amount="42,00,000",
        num_transfers=3, channel="UPI",
        beneficiary_account=AGG_ACC_01["account_no"],
        realisation_trigger="the callers blocked all communication",
        police_station=_station_unit.unit_name,
    )
    narrative_en = gen.generate(fir_id="LIVE_SCN1_FIR", prompt=prompt,
                                tier="A", crime_type=crime_type)
    fir_txt = header + narrative_en

    _write_live_files(base, fir_txt, narrative_en, gen, "LIVE_SCN1",
        crime_no, case_no, crime_type, complainant, accused, revealed, connects_to,
        ir_newly_revealed={"imeis": [CTRL_IMEI_01], "upis": [CTRL_UPI_01]},
        ir_money_trail=f"AGG_ACC_01 ({AGG_ACC_01['account_no']}) links to 3 historical ring cases. "
                       f"Controller IMEI {CTRL_IMEI_01} and UPI {CTRL_UPI_01} revealed by KYC check.",
        ir_connects_to=connects_to,
        fir_extension_rows={
            "accounts": [AGG_ACC_01],
            "rels_uses": [
                {"from_person_id": f"ACC:{reg.get_accused_master_id('P_SCN1_LIVE_A1') or 'TBD'}",
                 "to_object_id": AGG_ACC_01["account_no"],
                 "object_type": "accounts",
                 "source_caseid": crime_no,
                 "confidence": 1.0}
            ],
        },
        ir_extension_rows={
            "devices": [{"IMEI": CTRL_IMEI_01}],
            "upis":    [{"VPA": CTRL_UPI_01}],
            "rels_uses": [
                {"to_object_id": CTRL_IMEI_01, "object_type": "imeis",
                 "source_caseid": crime_no, "confidence": 1.0},
                {"to_object_id": CTRL_UPI_01, "object_type": "upis",
                 "source_caseid": crime_no, "confidence": 1.0},
            ],
        },
    )

# ---------------------------------------------------------------------------
# Scenario 2 live doc — Many Names, One Man reveal
# ---------------------------------------------------------------------------

def generate_scn2_live(gen: NarrativeGenerator, base: Path,
                       historical_crime_nos: List[str]) -> None:
    res = reg.get_live_reservation("LIVE_SCN2")
    crime_no = res["crime_no"]
    case_no  = res["case_no"]
    station_id = res["station_id"]
    reg_date = "2026-06-24"
    crime_type = "investment_scam"

    complainant = {"name": "Kavitha Reddy", "age": 34, "occupation": "Software Engineer",
                   "gender": "F"}
    accused_logical_id = "P_SCN2_A4"
    accused_master_id = reg.accused_master_id(accused_logical_id)
    accused = [{"person_id_label": "A1", "name": "Imran S.",
                "AccusedMasterID": accused_master_id,
                "age": 31, "gender": "M", "occupation": "Freelancer",
                "is_arrested": False,
                "_note": "Own AccusedMasterID; shares DEV_IMEI_02/UPI_02 with historical aliases via USES edges. Un-merged."}]

    revealed = {
        "accounts": [],
        "imeis":    [DEV_IMEI_02],
        "upis":     [UPI_02],
        "phones":   [PHONE_02],
    }
    connects_to = [
        {"historical_case_crime_no": cn,
         "via_identifier": DEV_IMEI_02,
         "identifier_type": "imei",
         "_note": "IMEI DEV_IMEI_02 shared across all alias-accused cases"}
        for cn in historical_crime_nos
    ] + [
        {"historical_case_crime_no": cn,
         "via_identifier": UPI_02,
         "identifier_type": "upi",
         "_note": "UPI_02 is the shared VPA across alias cases"}
        for cn in historical_crime_nos
    ]

    header = build_fir_header(
        station_id, crime_no, case_no,
        reg_date, "2026-06-20T00:00:00", "2026-06-23T23:59:00",
        complainant["name"], complainant["age"], complainant["occupation"],
        ["Imran S."], crime_type
    )
    prompt = (
        f"Write a realistic FIR narrative (200-300 words) for a fake investment / stock trading "
        f"scam in Bengaluru. The complainant is Kavitha Reddy, 34, software engineer. "
        f"She was added to a WhatsApp group promising high stock returns. "
        f"She invested Rs 15,00,000 and the accused 'Imran S.' communicated via "
        f"phone {PHONE_02} and UPI {UPI_02}. The device IMEI used was {DEV_IMEI_02}. "
        f"Include the phone number, UPI VPA, and IMEI verbatim."
    )
    narrative_en = gen.generate(fir_id="LIVE_SCN2_FIR", prompt=prompt,
                                tier="A", crime_type=crime_type)
    fir_txt = header + narrative_en

    _write_live_files(base, fir_txt, narrative_en, gen, "LIVE_SCN2",
        crime_no, case_no, crime_type, complainant, accused, revealed, connects_to,
        ir_newly_revealed={"imeis": [DEV_IMEI_02], "upis": [UPI_02], "phones": [PHONE_02]},
        ir_money_trail=f"Accused 'Imran S.' used phone {PHONE_02}, UPI {UPI_02}, IMEI {DEV_IMEI_02}. "
                       f"Platform entity resolution should merge with historical aliases.",
        ir_connects_to=connects_to
    )

# ---------------------------------------------------------------------------
# Scenario 3 live doc — Follow the Money bridge reveal
# ---------------------------------------------------------------------------

def generate_scn3_live(gen: NarrativeGenerator, base: Path,
                       historical_crime_nos: List[str]) -> None:
    res = reg.get_live_reservation("LIVE_SCN3")
    crime_no = res["crime_no"]
    case_no  = res["case_no"]
    station_id = res["station_id"]
    reg_date = "2026-06-25"
    crime_type = "investment_scam"

    complainant = {"name": "Sandeep Traders (Prop. Sandeep Kulkarni)", "age": 42,
                   "occupation": "MSME Owner", "gender": "M"}
    accused_logical_id = "P_SCN3_LIVE_A1"
    accused_master_id = reg.accused_master_id(accused_logical_id)
    accused = [{"person_id_label": "A1", "name": "Unknown / Under Investigation",
                "AccusedMasterID": accused_master_id,
                "age": 0, "gender": "M", "occupation": "Unknown",
                "is_arrested": False,
                "_note": "Own AccusedMasterID; un-merged"}]

    bridge_acc = BRIDGE_ACC_03["account_no"]
    revealed = {
        "accounts": [bridge_acc],
        "imeis":    [],
        "upis":     [],
        "phones":   [],
    }
    connects_to = [
        {"historical_case_crime_no": cn,
         "via_identifier": bridge_acc,
         "identifier_type": "account_no",
         "_note": "BRIDGE_ACC_03 is the shared bridge account; lights up existing Belagavi case"}
        for cn in historical_crime_nos
    ]

    header = build_fir_header(
        station_id, crime_no, case_no,
        reg_date, "2026-06-01T00:00:00", "2026-06-24T23:59:00",
        complainant["name"], 42, complainant["occupation"],
        ["Unknown / Under Investigation"], crime_type
    )
    prompt = (
        f"Write a realistic FIR narrative (200-300 words) for a fake investment scam in Dharwad. "
        f"The complainant is Sandeep Kulkarni who runs Sandeep Traders, an MSME. "
        f"He was defrauded of Rs 28,00,000 through a fake trading app. "
        f"Funds were routed through account {bridge_acc} "
        f"(IFSC {BRIDGE_ACC_03['ifsc']}, {BRIDGE_ACC_03['bank']}). "
        f"Include the account number verbatim."
    )
    narrative_en = gen.generate(fir_id="LIVE_SCN3_FIR", prompt=prompt,
                                tier="A", crime_type=crime_type)
    fir_txt = header + narrative_en

    # IR reveals BOTH the bridge account and the high-volume aggregation hub (KYC
    # Somashekar T), so the hub enters the graph as a mentioned node and Q3
    # "rank hub accounts" can surface it. Freezable downstream accounts are named too.
    _write_live_files(base, fir_txt, narrative_en, gen, "LIVE_SCN3",
        crime_no, case_no, crime_type, complainant, accused, revealed, connects_to,
        ir_newly_revealed={"accounts": [bridge_acc, HUB_ACC_03["account_no"]] + list(SCN3_FREEZABLE_ACCS)},
        ir_money_trail=(
            f"BRIDGE_ACC_03 ({bridge_acc}) links this case to the Belagavi digital arrest ring. "
            f"The highest-volume aggregation hub is account {HUB_ACC_03['account_no']} "
            f"(KYC: {HUB_ACC_03['kyc_name']}). Approximately Rs 6,20,000 still sits in downstream "
            f"accounts {', '.join(SCN3_FREEZABLE_ACCS)} with no outbound movement."
        ),
        ir_connects_to=connects_to
    )

# ---------------------------------------------------------------------------
# Scenario 4 live doc — Surge continuation
# ---------------------------------------------------------------------------

def generate_scn4_live(gen: NarrativeGenerator, base: Path,
                       historical_crime_nos: List[str]) -> None:
    res = reg.get_live_reservation("LIVE_SCN4")
    crime_no = res["crime_no"]
    case_no  = res["case_no"]
    station_id = res["station_id"]
    reg_date = "2026-06-26"
    crime_type = "task_scam"

    complainant = {"name": "Arjun K", "age": 21, "occupation": "Engineering Student",
                   "gender": "M"}
    accused_logical_id = "P_SCN4_LIVE_A1"
    accused_master_id = reg.accused_master_id(accused_logical_id)
    accused = [{"person_id_label": "A1", "name": "Unknown / Under Investigation",
                "AccusedMasterID": accused_master_id,
                "age": 0, "gender": "M", "occupation": "Unknown",
                "is_arrested": False,
                "_note": "Own AccusedMasterID; un-merged"}]

    # Use first device from SCN4 pool as the shared identifier
    shared_imei = DEV_POOL_04[0] if DEV_POOL_04 else "353816081234501"
    shared_ip_obj = IP_POOL_04[0] if IP_POOL_04 else {"ip": "103.21.58.1", "city": "Bengaluru"}
    shared_ip   = shared_ip_obj["ip"] if isinstance(shared_ip_obj, dict) else shared_ip_obj
    shared_ip_city = shared_ip_obj.get("city", "Bengaluru") if isinstance(shared_ip_obj, dict) else "Bengaluru"

    revealed = {
        "accounts": [],
        "imeis":    [shared_imei],
        "ips":      [shared_ip],
        "upis":     [],
        "phones":   [],
    }
    connects_to = [
        {"historical_case_crime_no": cn,
         "via_identifier": shared_imei,
         "identifier_type": "imei",
         "_note": "Shared IMEI from SCN4 pool links to burst ring cases"}
        for cn in historical_crime_nos[:3]  # connect to first 3 for brevity
    ]

    header = build_fir_header(
        station_id, crime_no, case_no,
        reg_date, "2026-06-25T09:00:00", "2026-06-25T18:00:00",
        complainant["name"], complainant["age"], complainant["occupation"],
        ["Unknown / Under Investigation"], crime_type
    )
    prompt = (
        f"Write a First Information Report narrative (200-300 words) in the style of a Karnataka "
        f"police FIR for an online job/task fraud case. "
        f"The complainant Arjun K, aged 21, an engineering student from Bengaluru, states that he "
        f"was approached through a Telegram message promising easy income by completing simple online "
        f"tasks such as rating products and liking videos. "
        f"Initially he received small payments which encouraged him to invest larger amounts. "
        f"He was asked to pay increasing deposits to unlock higher-tier tasks and eventual withdrawals. "
        f"After transferring a total of Rs 3,50,000 across multiple transactions, the operators "
        f"stopped responding and the application became inaccessible. "
        f"During investigation the following digital evidence was collected: "
        f"the mobile device used by the operator bears IMEI number {shared_imei}, "
        f"and the operator's internet connection was traced to IP address {shared_ip} "
        f"geolocated to {shared_ip_city}. "
        f"Both identifiers {shared_imei} and {shared_ip} must appear verbatim in the narrative. "
        f"Output only the FIR narrative text without any headings or preamble."
    )
    narrative_en = gen.generate(fir_id="LIVE_SCN4_FIR", prompt=prompt,
                                tier="A", crime_type=crime_type)
    fir_txt = header + narrative_en

    # The seized handler's device dump reveals the FULL shared pool (5 IMEIs, 4 IPs) plus
    # the controller UPI/account (live-only), so the live case joins the whole ring on
    # shared infrastructure and the controller becomes reachable. (Operator role-typed
    # Person nodes still require the extractor to parse a roster — tracked separately.)
    all_pool_ips = [ip["ip"] for ip in IP_POOL_04]
    # Role-typed operator roster (name | role | IMEI) + controller, parsed deterministically
    # at ingest into the org-chart nodes. Each operator uses one IMEI from the pool.
    operator_roster = [
        f"{op['name']} | {op['role']} | IMEI {DEV_POOL_04[op['imei_index']]}"
        for op in SCN4_OPERATORS
    ] + [f"Ring Controller | controller | UPI {SCN4_CONTROLLER_UPI}"]
    _write_live_files(base, fir_txt, narrative_en, gen, "LIVE_SCN4",
        crime_no, case_no, crime_type, complainant, accused, revealed, connects_to,
        ir_roster=operator_roster,
        ir_newly_revealed={
            "imeis": list(DEV_POOL_04),
            "ips": all_pool_ips,
            "upis": [SCN4_CONTROLLER_UPI],
            "accounts": [SCN4_CONTROLLER_ACC["account_no"]],
        },
        ir_money_trail=(
            f"Seized handler device dump links this case to the SCN4 burst ring via shared IMEIs "
            f"{', '.join(DEV_POOL_04)} and operator IPs {', '.join(all_pool_ips)} "
            f"(co-located, Electronic City Bengaluru). All commission payouts route to controller "
            f"UPI {SCN4_CONTROLLER_UPI} and account {SCN4_CONTROLLER_ACC['account_no']}. "
            f"Platform spike-detection should show weekly count rising sharply."
        ),
        ir_connects_to=connects_to
    )

# ---------------------------------------------------------------------------
# File writer helper
# ---------------------------------------------------------------------------

def _write_live_files(
    base: Path,
    fir_txt: str,
    narrative_en: str,
    gen: NarrativeGenerator,
    scenario_key: str,
    crime_no: str,
    case_no: str,
    crime_type: str,
    complainant: Dict,
    accused: List[Dict],
    revealed: Dict,
    connects_to: List[Dict],
    ir_newly_revealed: Dict,
    ir_money_trail: str,
    ir_connects_to: List[Dict],
    fir_extension_rows: Optional[Dict] = None,
    ir_extension_rows: Optional[Dict] = None,
    ir_roster: Optional[List[str]] = None,
) -> None:
    out = base / scenario_key.lower().replace("_", "_")
    out.mkdir(parents=True, exist_ok=True)

    # English FIR
    (out / "fir.txt").write_text(fir_txt, encoding="utf-8")

    # Kannada translation
    kn_prompt = (
        f"Translate the following First Information Report to Kannada. "
        f"Do NOT translate proper nouns, account numbers, IMEI numbers, phone numbers, "
        f"UPI IDs, or IP addresses — keep them exactly as-is in the translated text.\n\n"
        f"{fir_txt}"
    )
    kn_text = gen.generate(fir_id=f"{scenario_key}_KN", prompt=kn_prompt,
                           tier="A", crime_type=crime_type,
                           model_override="kannada")
    (out / "fir.kn.txt").write_text(kn_text, encoding="utf-8")

    # English back-translation of Kannada
    back_prompt = (
        f"Translate the following Kannada text back to English. "
        f"Do NOT translate proper nouns, account numbers, IMEI numbers, "
        f"phone numbers, UPI IDs, or IP addresses.\n\n"
        f"{kn_text}"
    )
    back_text = gen.generate(fir_id=f"{scenario_key}_BACK", prompt=back_prompt,
                             tier="B", crime_type=crime_type)
    (out / "fir.kn_backtranslation.txt").write_text(back_text, encoding="utf-8")

    # Investigation report
    ir_text = _build_ir_text(scenario_key, crime_no, ir_money_trail,
                             ir_newly_revealed, connects_to, ir_roster)
    (out / "investigation_report.txt").write_text(ir_text, encoding="utf-8")

    # fir.expected.json
    fir_expected = build_fir_expected(
        scenario_key=scenario_key,
        crime_no=crime_no,
        case_no=case_no,
        station_id=reg.get_live_reservation(scenario_key)["station_id"],
        crime_type=crime_type,
        complainant=complainant,
        accused_list=accused,
        revealed_identifiers=revealed,
        connects_to=connects_to,
        extension_rows=fir_extension_rows,
    )
    (out / "fir.expected.json").write_text(
        json.dumps(fir_expected, indent=2, ensure_ascii=False), encoding="utf-8")

    # ir.expected.json
    ir_expected = build_ir_expected(
        scenario_key=scenario_key,
        crime_no=crime_no,
        newly_revealed=ir_newly_revealed,
        money_trail_summary=ir_money_trail,
        connects_to=ir_connects_to,
        extension_rows=ir_extension_rows,
    )
    (out / "ir.expected.json").write_text(
        json.dumps(ir_expected, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_ir_text(scenario_key: str, crime_no: str,
                   money_trail: str,
                   newly_revealed: Dict,
                   connects_to: List[Dict],
                   roster: Optional[List[str]] = None) -> str:
    lines = [
        "INVESTIGATION REPORT",
        f"Case: {crime_no}",
        "",
        "MONEY TRAIL SUMMARY",
        money_trail,
        "",
        "NEWLY IDENTIFIED IDENTIFIERS",
    ]
    for id_type, ids in newly_revealed.items():
        for id_val in ids:
            lines.append(f"  {id_type}: {id_val}")
    if roster:
        # Deterministic block the ingest parser turns into role-typed operator nodes.
        lines.append("")
        lines.append("OPERATOR ROSTER (recovered from seized handler device)")
        for entry in roster:
            lines.append(f"  {entry}")
    lines.append("")
    lines.append("LINK ASSERTIONS (for validation)")
    for c in connects_to:
        lines.append(
            f"  -> Historical case {c.get('historical_case_crime_no','?')} "
            f"via {c.get('identifier_type','?')}: {c.get('via_identifier','?')}"
        )
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_all_live_docs(
    gen: NarrativeGenerator,
    output_dir: str = None,
    historical_crime_nos_by_scenario: Optional[Dict[str, List[str]]] = None,
) -> None:
    """
    Generate all 4 live demo document sets.

    Args:
        gen: NarrativeGenerator instance (Bedrock-connected)
        output_dir: root output directory (default config.OUTPUT_DIR)
        historical_crime_nos_by_scenario: {scenario_key: [crime_no, ...]}
            for link assertion generation. If None, uses placeholders.
    """
    base = Path(output_dir or config.OUTPUT_DIR) / "live_demo"
    base.mkdir(parents=True, exist_ok=True)

    h = historical_crime_nos_by_scenario or {}
    generate_scn1_live(gen, base, h.get("SCN1", ["SCN1_H01_PLACEHOLDER"]))
    generate_scn2_live(gen, base, h.get("SCN2", ["SCN2_H01_PLACEHOLDER"]))
    generate_scn3_live(gen, base, h.get("SCN3", ["SCN3_H01_PLACEHOLDER"]))
    generate_scn4_live(gen, base, h.get("SCN4", ["SCN4_H01_PLACEHOLDER"]))
