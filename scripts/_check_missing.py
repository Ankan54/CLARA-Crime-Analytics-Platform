"""Check exact missing tables and run targeted creates."""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parents[1] / ".env", override=True)
import os, psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).parents[1]
pw = os.environ["DB_PASSWORD"].strip('"\'')
url = "postgresql://{}:{}@{}:{}/{}?sslmode={}".format(
    os.environ["DB_USER"], pw, os.environ["DB_HOST"],
    os.environ["DB_PORT"], os.environ["DB_NAME"], os.environ["DB_SSL"]
)
conn = psycopg.connect(url, row_factory=dict_row, prepare_threshold=0, autocommit=False)

with conn.cursor() as cur:
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    existing = {r["table_name"].lower() for r in cur.fetchall()}

wanted = [
    "schemadefinition", "schemafield", "schemarelationship",
    "evidence", "investigationreport",
    "device", "account", "upihandle", "phonenumber",
    "transaction", "actsectionassociation", "appconfig",
]
print("Missing tables:", [t for t in wanted if t not in existing])
print("Present tables:", [t for t in wanted if t in existing])
conn.close()
