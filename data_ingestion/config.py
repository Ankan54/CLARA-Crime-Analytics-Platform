"""
config.py — Single source of truth for all data_ingestion constants, paths, and settings.
All other modules import from here.
"""
from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# ---------------------------------------------------------------------------
# Paths — source data
# ---------------------------------------------------------------------------
SQL_DIR      = ROOT / "sample_data" / "historical" / "sql"
DB_PATH      = ROOT / "sample_data" / "historical" / "db" / "ksp.sqlite"
SCHEMA_PATH  = ROOT / "sample_data" / "historical" / "db" / "schema.sql"
GRAPH_DIR    = ROOT / "sample_data" / "historical" / "graph"
NARRATIVES_PATH = ROOT / "sample_data" / "historical" / "vector" / "narratives.jsonl"
DOCS_DIR     = ROOT / "sample_data" / "historical" / "docs"
EVIDENCE_DIR = ROOT / "sample_data" / "historical" / "evidence"

# ---------------------------------------------------------------------------
# Paths — state / output
# ---------------------------------------------------------------------------
STATE_DIR     = ROOT / ".ingest_checkpoints"
BLOB_MANIFEST = STATE_DIR / "blob_manifest.json"
FAILURES_FILE = STATE_DIR / "failures.json"

# ---------------------------------------------------------------------------
# Pinecone
# ---------------------------------------------------------------------------
PINECONE_INDEX  = os.getenv("PINECONE_INDEX", "ksp-crime-intel")
PINECONE_DIM    = 1536
PINECONE_METRIC = "cosine"
PINECONE_CLOUD  = "aws"
PINECONE_REGION = "us-east-1"

# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------
NEO4J_URI      = os.getenv("NEO4J_URI", "")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_BATCH    = 500

# ---------------------------------------------------------------------------
# Bedrock
# ---------------------------------------------------------------------------
BEDROCK_EMBEDDING_MODEL = os.getenv("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v1")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
EMBED_TEXT_MAX_CHARS = 40_000   # ponytail: Titan limit ~50k; 40k gives headroom

# ---------------------------------------------------------------------------
# Pinecone upsert
# ---------------------------------------------------------------------------
PINECONE_BATCH = 100

# ---------------------------------------------------------------------------
# Zoho Catalyst / Stratus
# ---------------------------------------------------------------------------
ZOHO_PROJECT_ID     = os.getenv("ZOHO_CATALYST_PROJECT_ID", "")
ZOHO_PROJECT_KEY    = os.getenv("ZOHO_CATALYST_PROJECT_KEY", "")
ZOHO_ENVIRONMENT    = os.getenv("ZOHO_CATALYST_ENVIRONMENT", "Development")
ZOHO_PROJECT_DOMAIN = os.getenv("ZOHO_CATALYST_PROJECT_DOMAIN", "https://api.catalyst.zoho.in")
ZOHO_CLIENT_ID      = os.getenv("ZOHO_CATALYST_CLIENT_ID", "")
ZOHO_CLIENT_SECRET  = os.getenv("ZOHO_CATALYST_CLIENT_SECRET", "")
ZOHO_REFRESH_TOKEN  = os.getenv("ZOHO_CATALYST_REFRESH_TOKEN", "")
ZOHO_STRATUS_BUCKET = os.getenv("ZOHO_STRATUS_BUCKET", "ksp-data-files")

# ---------------------------------------------------------------------------
# Required env var names (for preflight check)
# ---------------------------------------------------------------------------
REQUIRED_ENV_VARS = [
    "NEO4J_URI", "NEO4J_PASSWORD",
    "PINECONE_API_KEY",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "ZOHO_CATALYST_PROJECT_ID", "ZOHO_CATALYST_PROJECT_KEY",
    "ZOHO_CATALYST_CLIENT_ID", "ZOHO_CATALYST_CLIENT_SECRET",
    "ZOHO_CATALYST_REFRESH_TOKEN",
    "ZOHO_STRATUS_BUCKET",
    "DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD",
]

# ---------------------------------------------------------------------------
# Vector metadata: canonical field names shared by vector_store + export.py
# ---------------------------------------------------------------------------
VECTOR_METADATA_FIELDS = [
    # identity / join
    "node_id", "doc_type", "crime_no", "case_master_id", "fir_logical_id", "blob_uri",
    # geography
    "district", "police_station",
    # temporal
    "crime_registered_date", "date_of_offence", "report_date", "registered_year",
    # classification
    "crime_type", "crime_subhead", "crime_head", "case_category", "gravity", "case_status",
    # legal
    "acts", "sections",
    # financial
    "amount_involved", "amount_band",
    # people counts (low-PII)
    "accused_count", "accused_known", "any_arrested", "victim_count",
    # police personnel
    "io_officer", "io_rank", "io_designation", "court",
    # IR-specific
    "is_live",
]

# ---------------------------------------------------------------------------
# Amount band helper
# ---------------------------------------------------------------------------
def amount_band(n: int | float | None) -> str:
    if n is None:
        return ""
    n = int(n)
    if n < 100_000:
        return "<1L"
    if n < 500_000:
        return "1L-5L"
    if n < 1_000_000:
        return "5L-10L"
    if n < 5_000_000:
        return "10L-50L"
    return ">50L"

# ---------------------------------------------------------------------------
# Map crime sub-head label -> crime_type code  (for IR records which have no
# crime_type in the DB; the sub-head name IS stored via CrimeMinorHeadID)
# ---------------------------------------------------------------------------
CRIME_SUBHEAD_TO_TYPE: dict[str, str] = {
    "Digital Arrest / Fake Official Threat":  "digital_arrest",
    "Fake Investment / Stock Market Fraud":   "investment_scam",
    "Online Task / Job Scam":                 "task_scam",
    "UPI Payment Fraud":                      "upi_fraud",
    "OTP Theft / SIM Swap Fraud":             "otp_fraud",
    "Predatory Loan App Fraud":               "loan_app",
    "Fake Job / Placement Fraud":             "job_scam",
    "Sextortion / Honey Trap":                "sextortion",
    "Phishing / Vishing / Fake Bank":         "phishing",
    "Mule Account / Money Mule Recruitment":  "mule_account",
}
