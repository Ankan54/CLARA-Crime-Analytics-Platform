"""
config.py — Single source of truth for all constants, seeds, model IDs, and volume targets.
All other modules import from here; change a value once, it propagates everywhere.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
RANDOM_SEED = 42
DEMO_DATE_STR = "2026-06-26"   # "today" for all relative date calculations

# ---------------------------------------------------------------------------
# AWS Bedrock model IDs (read from .env; placeholders are fallback defaults)
# ---------------------------------------------------------------------------
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "YOUR_MODEL_ID_HERE")       # English narratives
BEDROCK_MODEL_ID_KANNADA = os.getenv("BEDROCK_MODEL_ID_KANNADA", "YOUR_STRONGER_MODEL_ID_HERE")  # Kannada translations

# ---------------------------------------------------------------------------
# Validation embedding model (sentence-transformers)
# ---------------------------------------------------------------------------
VALIDATION_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Narrative generation settings
# ---------------------------------------------------------------------------
NARRATIVE_TEMPERATURE_TIER_A = 0.3   # planted same-MO cluster — stay tight
NARRATIVE_TEMPERATURE_TIER_B = 0.7   # same type, different sub-script
NARRATIVE_TEMPERATURE_TIER_C = 0.7   # different crime types
NARRATIVE_MAX_TOKENS = 2048
NARRATIVE_CONTENT_REPAIR_RETRIES = 3  # re-prompt attempts if identifiers missing

# LangChain/Bedrock client-side rate limiting + retries
BEDROCK_REQUESTS_PER_SECOND = 1.0   # proactive throttle to avoid rate-limit bursts
BEDROCK_MAX_BUCKET = 3               # max burst size for token bucket
LLM_MAX_RETRIES = 6                  # retry budget for transient model errors
LLM_TIMEOUT = 120                    # read timeout in seconds

# ---------------------------------------------------------------------------
# Pipeline directories
# ---------------------------------------------------------------------------
NARRATIVE_CACHE_DIR = ".narrative_cache"
CHECKPOINT_DIR = ".checkpoints"
OUTPUT_STAGING_DIR = "sample_data.tmp"
OUTPUT_DIR = "sample_data"
OUTPUT_BACKUP_DIR = "sample_data.bak"
FAILURES_FILE = "failures.json"
LOG_FILE = "generation.log"

# ---------------------------------------------------------------------------
# Volume targets (validation checks within ±10%)
# ---------------------------------------------------------------------------
TARGET_FIRS_TOTAL = 65
TARGET_FIRS_HISTORICAL = 61
TARGET_FIRS_LIVE = 4
TARGET_FIRS_SCENARIO_CRITICAL = 27   # Scn1:3 + Scn2:3 + Scn3:2 + Scn4_burst:14 + Scn4_baseline:5
TARGET_FIRS_BACKGROUND = 34

TARGET_INVESTIGATION_REPORTS_TOTAL = 30
TARGET_INVESTIGATION_REPORTS_HISTORICAL = 31
TARGET_INVESTIGATION_REPORTS_LIVE = 4

TARGET_PERSONS = 110        # victims ~65 + criminal/mule/operator ~45
TARGET_ACCOUNTS = 57
TARGET_TRANSACTIONS = 101
TARGET_DEVICES = 7
TARGET_PHONES = 2
TARGET_UPIS = 9
TARGET_IPS = 4
TARGET_WALLETS = 1
TARGET_LEGAL_SECTIONS = 10
TARGET_LEGAL_ELEMENTS = 35
TARGET_EVIDENCE_TYPES = 15
TARGET_PRECEDENTS = 12
TARGET_IPC_SECTIONS = 4     # IPC 420, 416, 419, 415

VOLUME_TOLERANCE = 0.10     # ±10%

# ---------------------------------------------------------------------------
# Scenario-specific FIR counts
# ---------------------------------------------------------------------------
SCN1_HISTORICAL_FIRS = 3    # Mysuru, Mangaluru, Hubballi
SCN2_HISTORICAL_FIRS = 3    # loan_app / otp_fraud / job_scam
SCN3_HISTORICAL_FIRS = 2    # Belagavi digital-arrest + HUB_ACC_03 anchor
SCN4_BURST_FIRS = 14        # last 21 days
SCN4_BASELINE_FIRS = 5      # Jan–May 2026 (independent identifiers)

# ---------------------------------------------------------------------------
# Temporal anchors (all relative to DEMO_DATE)
# ---------------------------------------------------------------------------
SCN4_BURST_WINDOW_DAYS = 21          # burst within last N days
SCN4_BASELINE_START_MONTHS_AGO = 6   # baseline spread from ~6 months ago
HISTORICAL_WINDOW_MONTHS = 12        # background cases span last 12 months
SCN2_OLDEST_CASE_YEAR = 2024         # earliest alias case

# Scenario 1 coordinated cash-out window (all within 2 hours)
SCN1_CASHOUT_WINDOW_MINUTES = 120

# Scenario 3 rapid layering
SCN3_LAYERING_WINDOW_MINUTES = 15    # sub-₹1L splits within this window

# ---------------------------------------------------------------------------
# Financial amounts
# ---------------------------------------------------------------------------
SCN1_LIVE_AMOUNT = 4200000    # Dr. Anand Rao  ₹42L
SCN2_AMOUNTS = [150000, 400000, 800000, 1500000]   # escalation per case
SCN3_LIVE_AMOUNT = 2800000    # Sandeep Traders ₹28L
SCN3_FREEZABLE_AMOUNT = 620000  # ~₹6.2L still sitting
SCN4_LIVE_AMOUNT = 350000       # Arjun K ₹3.5L

# ---------------------------------------------------------------------------
# Background FIR district weighting
# ---------------------------------------------------------------------------
BENGALURU_WEIGHT = 0.40        # ~40% background FIRs in Bengaluru

# ---------------------------------------------------------------------------
# Background crime-type targets (overall corpus, after subtracting scenario-critical)
# Remaining after scenario critical cases:
#   task_scam total ~16: burst 14 + baseline 5 = 19 scenario; cap it at ~16 in corpus
#   digital_arrest total ~10: Scn1 uses 4; background ~6
#   investment_scam ~10: Scn2 uses 1; background ~9
#   upi_fraud ~10: Scn3 uses 1; background ~9
#   loan_app/otp_fraud/job_scam ~9: Scn2 uses 3; background ~6
#   sextortion/phishing/mule_account ~10: all background
# ---------------------------------------------------------------------------
BACKGROUND_CRIME_TYPE_DISTRIBUTION = {
    "digital_arrest": 6,       # Tier-B variants (NCB/customs pretext)
    "investment_scam": 6,
    "upi_fraud": 6,
    "task_scam": 2,            # 5 baseline already counted in scenario; 2 extra
    "loan_app": 2,
    "otp_fraud": 2,
    "job_scam": 2,
    "sextortion": 3,
    "phishing": 3,
    "mule_account": 2,
}
# Total should sum to TARGET_FIRS_BACKGROUND = 34

# ---------------------------------------------------------------------------
# Karnataka / South-Indian name pools  (used by Faker wrappers)
# ---------------------------------------------------------------------------
SOUTH_INDIAN_FIRST_NAMES_MALE = [
    "Anand", "Arjun", "Sandeep", "Venkatesh", "Manjunath", "Suresh", "Ravi",
    "Kiran", "Praveen", "Ramesh", "Ganesh", "Harish", "Vinod", "Mohan",
    "Shiva", "Arun", "Pradeep", "Naveen", "Deepak", "Rohit", "Sanjay",
    "Ajay", "Vijay", "Rajesh", "Mahesh", "Dinesh", "Girish", "Satish",
    "Nagaraj", "Basavaraj", "Siddaraju", "Virupaksha", "Channappa", "Hosakote",
    "Shivarudrappa", "Thimmaiah", "Muniraj", "Kantharaju", "Siddappa",
]
SOUTH_INDIAN_FIRST_NAMES_FEMALE = [
    "Priya", "Lakshmi", "Kavitha", "Shobha", "Rekha", "Sunitha", "Geetha",
    "Radha", "Usha", "Meena", "Nirmala", "Savitha", "Pushpa", "Padma",
    "Jayalaxmi", "Bhavana", "Deepa", "Asha", "Sarala", "Vimala",
    "Mangala", "Shakuntala", "Ambika", "Girija", "Kamala", "Shanthi",
    "Vasantha", "Nalini", "Hema", "Renuka",
]
SOUTH_INDIAN_LAST_NAMES = [
    "Rao", "Nair", "Reddy", "Sharma", "Naidu", "Gowda", "Hegde",
    "Shetty", "Patel", "Krishnamurthy", "Venkataraman", "Subramaniam",
    "Iyer", "Iyengar", "Pillai", "Menon", "Kamath", "Kulkarni",
    "Patil", "Desai", "Shastri", "Murthy", "Acharya", "Bhat",
    "Gaonkar", "Lamani", "Veeranna", "Basappa", "Mallaiah",
]

# Alias variants for Scenario 2 offender
SCN2_ALIAS_NAMES = [
    "Imran S.",
    "Imraan Sheikh",
    "I. Shaikh",
    "Imran Shek",
]
SCN2_DECOY_NAME = "Imran Sheikh"   # same-sounding but NOT the offender

# Scenario 1 live victim
SCN1_LIVE_VICTIM_NAME = "Dr. Anand Rao"
SCN1_LIVE_VICTIM_AGE = 58

# Scenario 3 live victim
SCN3_LIVE_VICTIM_NAME = "Sandeep Traders"   # MSME

# Scenario 4 live victim
SCN4_LIVE_VICTIM_NAME = "Arjun K"
SCN4_LIVE_VICTIM_AGE = 21

# ---------------------------------------------------------------------------
# Role-conditioned demographics
# ---------------------------------------------------------------------------
DEMOGRAPHICS_BY_ROLE = {
    "victim_digital_arrest": {
        "age_range": (45, 70),
        "gender": ["Male", "Female"],
        "occupations": ["Retired Professor", "Retired Engineer", "Doctor", "Retired IAS Officer",
                        "Chartered Accountant", "Senior Manager", "Businessman"],
    },
    "victim_task_scam": {
        "age_range": (18, 28),
        "gender": ["Male", "Female"],
        "occupations": ["Student", "Fresher", "Part-time Worker", "Job Seeker",
                        "Engineering Student", "MBA Student", "Unemployed Graduate"],
    },
    "victim_investment_scam": {
        "age_range": (28, 45),
        "gender": ["Male", "Female"],
        "occupations": ["Software Engineer", "IT Professional", "Bank Employee",
                        "Teacher", "Government Employee", "Small Business Owner"],
    },
    "victim_upi_fraud": {
        "age_range": (25, 55),
        "gender": ["Male", "Female"],
        "occupations": ["Shop Owner", "Trader", "Businessman", "Contractor",
                        "Transport Operator", "MSME Owner"],
    },
    "mule": {
        "age_range": (18, 30),
        "gender": ["Male", "Female"],
        "occupations": ["Student", "Homemaker", "Daily Wage Worker", "Job Seeker",
                        "Auto Driver", "Delivery Worker"],
    },
    "operator": {
        "age_range": (20, 35),
        "gender": ["Male"],
        "occupations": ["Unemployed", "Freelancer", "Small Trader", "Part-time Worker",
                        "Call Centre Agent", "Data Entry Operator"],
    },
    "controller": {
        "age_range": (28, 45),
        "gender": ["Male"],
        "occupations": ["Businessman", "Money Lender", "Property Dealer",
                        "Consultant", "Finance Broker"],
    },
}

# =============================================================================
# KSP SCHEMA INTEGRATION CONSTANTS
# Added to conform the SQL store to the KSP FIR ER schema.
# =============================================================================

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
STATE_ID_KARNATAKA = 29

# ---------------------------------------------------------------------------
# Case Category codes (used in CrimeNo format and CaseCategory FK)
# ---------------------------------------------------------------------------
CASE_CATEGORY_FIR       = 1   # standard FIR (majority of cases)
CASE_CATEGORY_UDR       = 3   # unnatural death report
CASE_CATEGORY_PAR       = 4   # police action report
CASE_CATEGORY_ZERO_FIR  = 8   # zero FIR (filed at non-jurisdictional station)

# All generated cases use FIR category unless overridden
DEFAULT_CASE_CATEGORY = CASE_CATEGORY_FIR

# ---------------------------------------------------------------------------
# CrimeNo format constants
# Format: C(1) + DistrictID(4) + UnitID(4) + Year(4) + Serial(5) = 18 digits
# Validation regex: ^[1348]\d{4}\d{4}\d{4}\d{5}$
# ---------------------------------------------------------------------------
CRIME_NO_LENGTH         = 18
CRIME_NO_CATEGORY_CHARS = 1
CRIME_NO_DISTRICT_CHARS = 4
CRIME_NO_UNIT_CHARS     = 4
CRIME_NO_YEAR_CHARS     = 4
CRIME_NO_SERIAL_CHARS   = 5
CRIME_NO_REGEX          = r'^[1348]\d{17}$'    # 1 category + 17 digits = 18 total
CASE_NO_LENGTH          = 9                    # last 9 digits of CrimeNo

# ---------------------------------------------------------------------------
# ChargesheetDetails cstype distribution
# Reflects the low cyber-crime detection rate in Karnataka.
# cstype: C=Undetected, A=Chargesheet, B=False (mistaken/withdrawn)
# ---------------------------------------------------------------------------
CSTYPE_DISTRIBUTION = {
    "C": 0.85,   # Undetected (~85%) — typical for cyber fraud
    "A": 0.10,   # Chargesheet (~10%) — cases with identified accused
    "B": 0.05,   # False (~5%) — mistaken/withdrawn
}

# ---------------------------------------------------------------------------
# INT PK base ranges (mirrors id_registry.py — single source for docs)
# ---------------------------------------------------------------------------
PK_BASE_CASE_MASTER  = 1_000_000
PK_BASE_ACCUSED      = 2_000_000
PK_BASE_COMPLAINANT  = 3_000_000
PK_BASE_VICTIM       = 4_000_000
PK_BASE_REPORT       = 5_000_000
PK_BASE_EXT_OBJ      = 6_000_000

# ---------------------------------------------------------------------------
# KSP master volume targets
# ---------------------------------------------------------------------------
TARGET_KSP_STATES         = 1
TARGET_KSP_DISTRICTS      = 31
TARGET_KSP_UNITS          = 30   # police stations
TARGET_KSP_EMPLOYEES      = 12   # IO officers
TARGET_KSP_COURTS         = 10
TARGET_KSP_CASE_CATEGORIES = 4
TARGET_KSP_CRIME_HEADS    = 2
TARGET_KSP_CRIME_SUB_HEADS = 10
TARGET_KSP_ACTS            = 5
TARGET_KSP_SECTIONS        = 10
TARGET_KSP_CASTES          = 5
TARGET_KSP_RELIGIONS       = 5
TARGET_KSP_OCCUPATIONS     = 39

# ---------------------------------------------------------------------------
# Output subdirectory paths for KSP SQL core vs extension
# ---------------------------------------------------------------------------
OUTPUT_SQL_KSP_DIR        = "sql/ksp"
OUTPUT_SQL_KSP_MASTER_DIR = "sql/ksp/master"
OUTPUT_SQL_EXT_DIR        = "sql/extension"

# ---------------------------------------------------------------------------
# NOTE on demographic analysis:
# CasteID and ReligionID are populated on ComplainantDetails, Victim, and
# Accused rows for KSP schema conformance ONLY.
# The platform's demographic analysis feature MUST segment exclusively by:
#   age, gender, occupation, education
# Caste and religion MUST be excluded from all analysis, visualisation, and
# exportable reports. This rule is enforced by validate.py.
# ---------------------------------------------------------------------------
DEMOGRAPHICS_ANALYSIS_FIELDS = ["age", "gender", "occupation", "education"]
DEMOGRAPHICS_EXCLUDED_FIELDS = ["caste_id", "religion_id"]
