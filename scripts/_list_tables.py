"""Check pipeline-specific tables"""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parents[1] / ".env", override=True)
import os, psycopg
from psycopg.rows import dict_row

pw = os.environ["DB_PASSWORD"].strip('"\'')
url = "postgresql://{}:{}@{}:{}/{}?sslmode={}".format(
    os.environ["DB_USER"], pw, os.environ["DB_HOST"],
    os.environ["DB_PORT"], os.environ["DB_NAME"], os.environ["DB_SSL"]
)
conn = psycopg.connect(url, row_factory=dict_row, prepare_threshold=0)
with conn.cursor() as cur:
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
          AND (table_name ILIKE '%pipeline%'
            OR table_name ILIKE '%batch%'
            OR table_name ILIKE '%run%'
            OR table_name ILIKE '%schema%'
            OR table_name ILIKE '%entity%'
            OR table_name ILIKE '%review%'
            OR table_name ILIKE '%evidence%'
            OR table_name ILIKE '%transaction%'
            OR table_name ILIKE '%account%'
            OR table_name ILIKE '%upload%')
        ORDER BY table_name
    """)
    rows = cur.fetchall()
    if rows:
        for r in rows: print(r["table_name"])
    else:
        print("(none found)")
conn.close()
