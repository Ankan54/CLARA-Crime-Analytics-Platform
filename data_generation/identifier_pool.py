"""
identifier_pool.py — All hard-coded shared identifiers for the four demo scenarios.

Split into:
  - HISTORICAL: pre-loaded into the platform's base graph
  - LIVE_ONLY: appear ONLY in held-back live-demo documents
  - DECOYS: exist in pre-loaded data but must NOT link to scenario cases

NEVER add CTRL_UPI_01 or CTRL_IMEI_01 to any historical FIR/transaction.
NEVER add any pooled identifier to background noise FIRs.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Scenario 1 — Digital Arrest Ring (TRAI/CBI/Skype MO)
# ---------------------------------------------------------------------------

# Aggregation account — pre-loaded with NO kyc_name and NO owner Person node.
# All 4 cases' transaction trails route here. Live IR reveals the KYC name.
AGG_ACC_01 = {
    "account_no": "9842017633250001",
    "bank": "HDFC Bank",
    "ifsc": "HDFC0004217",       # HDFC0 + 6 char branch code
    "branch_district": "Bengaluru Urban",
    "kyc_name": "",              # deliberately blank in pre-loaded data
    "is_flagged_mule": True,
}
# Intermediate collection accounts (one per victim case — different each case)
SCN1_COLLECT_ACCS = [
    {"account_no": "7701234567890011", "bank": "Canara Bank",    "ifsc": "CNRB0003012", "branch_district": "Mysuru"},
    {"account_no": "7701234567890022", "bank": "State Bank of India", "ifsc": "SBIN0040121", "branch_district": "Mangaluru"},
    {"account_no": "7701234567890033", "bank": "Karnataka Bank", "ifsc": "KTKM0000221", "branch_district": "Hubballi-Dharwad"},
]

# Live-only identifiers — NEVER in pre-loaded data
CTRL_IMEI_01 = "867537042195016"        # controller's phone IMEI
CTRL_UPI_01  = "raghu.ctrl@ybl"         # controller's UPI VPA

# The mule Person node is created only when the live IR is ingested
SCN1_MULE_KYC_NAME = "Ravi Kumar G"     # revealed by live IR
SCN1_MULE_AADHAAR = "4821 5630 7192"    # synthetic Aadhaar — revealed by live IR

# ---------------------------------------------------------------------------
# Scenario 2 — Many Names, One Man (entity resolution)
# ---------------------------------------------------------------------------

DEV_IMEI_02  = "351756078901234"        # the shared IMEI binding all 4 alias nodes
UPI_02       = "imran.transactions@axl" # the shared UPI VPA
PHONE_02     = "9611234567"             # the shared phone number

# Alias node names (each gets a distinct person_id — NO pre-merging)
SCN2_ALIAS_NODES = [
    {"full_name": "Imraan Sheikh",  "person_id": "P_SCN2_A1", "crime_type": "loan_app",         "case_year": 2024},
    {"full_name": "I. Shaikh",      "person_id": "P_SCN2_A2", "crime_type": "otp_fraud",        "case_year": 2025},
    {"full_name": "Imran Shek",     "person_id": "P_SCN2_A3", "crime_type": "job_scam",         "case_year": 2025},
    {"full_name": "Imran S.",       "person_id": "P_SCN2_A4", "crime_type": "investment_scam",  "case_year": 2026},  # live
]

# Separate mule accounts per alias case (not the same account — connection is via the IMEI/UPI/Phone)
SCN2_MULE_ACCS = [
    {"account_no": "8810987654321001", "bank": "Axis Bank",    "ifsc": "UTIB0002311", "branch_district": "Bengaluru Urban"},
    {"account_no": "8810987654321002", "bank": "IndusInd Bank","ifsc": "INDB0000412", "branch_district": "Tumakuru"},
    {"account_no": "8810987654321003", "bank": "Kotak Mahindra Bank", "ifsc": "KKBK0001234", "branch_district": "Bengaluru Urban"},
]

# CDR reveal — new phone number that appears on DEV_IMEI_02 in the live IR
SCN2_NEW_PHONE = "9622345678"

# Decoy: same-sounding name but completely independent identifiers (must NOT resolve)
SCN2_DECOY_PERSON = {
    "full_name": "Imran Sheikh",
    "person_id": "P_SCN2_DECOY",
    "phone":  "9855667788",     # INDEPENDENT
    "imei":   "490154203237518",# INDEPENDENT
    "upi":    "imranshk.real@okicici",  # INDEPENDENT
    "account_no": "6620011223344001",   # INDEPENDENT
}

# ---------------------------------------------------------------------------
# Scenario 3 — Follow the Money (layering / bridge)
# ---------------------------------------------------------------------------

# Bridge account — pre-loaded in the Belagavi digital-arrest case
BRIDGE_ACC_03 = {
    "account_no": "5530123456789001",
    "bank": "Union Bank of India",
    "ifsc": "UBIN0557301",
    "branch_district": "Belagavi",
    "is_flagged_mule": True,
}

# Hub account — highest-volume aggregation point (historical + live)
HUB_ACC_03 = {
    "account_no": "5530123456789002",
    "bank": "ICICI Bank",
    "ifsc": "ICIC0001173",
    "branch_district": "Bengaluru Urban",
    "kyc_name": "Somashekar T",       # hub operator name
    "is_flagged_mule": True,
}

# USDT crypto wallet — final cash-out endpoint
WALLET_03 = {
    "address": "TR7NHqjeKQxGTCi8q8ZY4pL17cMd3wqv9N",
    "chain": "USDT-TRC20",
}

# Mule accounts in Scenario 3 layering ring (sub-₹1L tranche destinations)
SCN3_MULE_ACCS = [
    {"account_no": "5530123456789011", "bank": "Canara Bank",    "ifsc": "CNRB0004523", "branch_district": "Dharwad"},
    {"account_no": "5530123456789012", "bank": "State Bank of India", "ifsc": "SBIN0050234", "branch_district": "Belagavi"},
    {"account_no": "5530123456789013", "bank": "Karnataka Bank", "ifsc": "KTKM0000512", "branch_district": "Vijayapura"},
    {"account_no": "5530123456789014", "bank": "Bank of Baroda", "ifsc": "BARB0BELAGU", "branch_district": "Belagavi"},
    {"account_no": "5530123456789015", "bank": "HDFC Bank",      "ifsc": "HDFC0003451", "branch_district": "Shivamogga"},
]

# Freezable accounts (have inbound but no subsequent outbound)
SCN3_FREEZABLE_ACCS = ["5530123456789013", "5530123456789014"]   # ~₹6.2L combined

# ---------------------------------------------------------------------------
# Scenario 4 — The Surge (task-scam ring + baseline)
# ---------------------------------------------------------------------------

# 5 IMEIs shared among ring operators
DEV_POOL_04 = [
    "353816081234501",
    "353816081234502",
    "353816081234503",
    "353816081234504",
    "353816081234505",
]

# 4 IPs co-located at Electronic City (~12.84, 77.68)
IP_POOL_04 = [
    {"ip": "103.74.19.141", "lat": 12.8384, "long": 77.6814, "city": "Electronic City, Bengaluru"},
    {"ip": "103.74.19.142", "lat": 12.8391, "long": 77.6821, "city": "Electronic City, Bengaluru"},
    {"ip": "103.74.19.143", "lat": 12.8376, "long": 77.6808, "city": "Electronic City, Bengaluru"},
    {"ip": "103.74.19.144", "lat": 12.8379, "long": 77.6815, "city": "Electronic City, Bengaluru"},
]

# 7 mule accounts shared across burst FIRs
MULE_SET_04 = [
    {"account_no": "4440988776655001", "bank": "Paytm Payments Bank", "ifsc": "PYTM0123001", "branch_district": "Bengaluru Urban"},
    {"account_no": "4440988776655002", "bank": "Airtel Payments Bank","ifsc": "AIRP0001001", "branch_district": "Bengaluru Urban"},
    {"account_no": "4440988776655003", "bank": "Fino Payments Bank",  "ifsc": "FINO0001001", "branch_district": "Bengaluru Urban"},
    {"account_no": "4440988776655004", "bank": "State Bank of India", "ifsc": "SBIN0060011", "branch_district": "Bengaluru Urban"},
    {"account_no": "4440988776655005", "bank": "Canara Bank",         "ifsc": "CNRB0005001", "branch_district": "Bengaluru Urban"},
    {"account_no": "4440988776655006", "bank": "ICICI Bank",          "ifsc": "ICIC0001801", "branch_district": "Bengaluru Urban"},
    {"account_no": "4440988776655007", "bank": "HDFC Bank",           "ifsc": "HDFC0007901", "branch_district": "Bengaluru Urban"},
]

# Mule UPI IDs from the pool (each mule acc gets one)
MULE_UPI_04 = [
    "earnfast001@paytm",
    "taskpro002@airtel",
    "dailywork003@fino",
    "quickjob004@oksbi",
    "simpletask005@okhdfcbank",
    "worker006@icici",
    "jobapp007@hdfcbank",
]

# Controller identifiers for Scenario 4 (revealed in live IR)
SCN4_CONTROLLER_UPI = "ring.ctrl04@ybl"
SCN4_CONTROLLER_ACC = {
    "account_no": "4440988776655099",
    "bank": "Karnataka Bank",
    "ifsc": "KTKM0000899",
    "branch_district": "Bengaluru Urban",
}

# Operator roster (revealed in live IR from seized device)
SCN4_OPERATORS = [
    {"name": "Ravi V",      "role": "caller",       "imei_index": 0},
    {"name": "Suresh M",    "role": "mule_handler", "imei_index": 1},
    {"name": "Venkat R",    "role": "recruiter",    "imei_index": 2},
    {"name": "Deepak N",    "role": "caller",       "imei_index": 3},
    {"name": "Harish K",    "role": "mule_handler", "imei_index": 4},
]

# ---------------------------------------------------------------------------
# Decoy cases (similar MO but ZERO shared identifiers with Scenario 1)
# ---------------------------------------------------------------------------
SCN1_DECOY = {
    "account_no": "DECOY00000000001",           # completely independent
    "bank": "Yes Bank",
    "ifsc": "YESB0000741",
    "branch_district": "Hassan",
    "pretext": "TRAI hybrid — international call routing fraud",
    "platform": "Google Meet",                  # not Skype
}

# All pooled identifier values in a flat set for contamination checking
ALL_POOL_IDENTIFIERS: set[str] = {
    AGG_ACC_01["account_no"],
    CTRL_IMEI_01, CTRL_UPI_01,
    DEV_IMEI_02, UPI_02, PHONE_02,
    SCN2_DECOY_PERSON["phone"], SCN2_DECOY_PERSON["imei"],
    SCN2_DECOY_PERSON["upi"],   SCN2_DECOY_PERSON["account_no"],
    BRIDGE_ACC_03["account_no"], HUB_ACC_03["account_no"], WALLET_03["address"],
    *[a["account_no"] for a in SCN1_COLLECT_ACCS],
    *[a["account_no"] for a in SCN2_MULE_ACCS],
    *[a["account_no"] for a in SCN3_MULE_ACCS],
    *DEV_POOL_04,
    *[ip["ip"] for ip in IP_POOL_04],
    *[a["account_no"] for a in MULE_SET_04],
    *MULE_UPI_04,
    SCN4_CONTROLLER_UPI, SCN4_CONTROLLER_ACC["account_no"],
    SCN2_NEW_PHONE,
}

# Live-only identifiers — the validation stage checks these are ABSENT from historical data
LIVE_ONLY_IDENTIFIERS: set[str] = {
    CTRL_IMEI_01,
    CTRL_UPI_01,
    SCN4_CONTROLLER_UPI,
    SCN4_CONTROLLER_ACC["account_no"],
}
