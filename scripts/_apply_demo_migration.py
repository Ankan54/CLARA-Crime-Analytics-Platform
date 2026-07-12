"""Apply the demo scenario migration to the database using psycopg2 execute on the full SQL."""
from dotenv import load_dotenv
load_dotenv(override=True)

import os
import psycopg2

conn = psycopg2.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"].strip('"'),
    sslmode=os.environ["DB_SSL"],
    connect_timeout=15,
)
conn.autocommit = True
cur = conn.cursor()

with open("backend/migrations/002_demo_scenario_tables.sql", "r") as f:
    sql = f.read()

# Execute the entire migration as one script
try:
    cur.execute(sql)
    print("Migration applied successfully.")
except Exception as e:
    print(f"ERROR: {e}")

# Verify tables exist
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename IN ('demoscenariostate', 'demoresetoperation', 'ingestartifact', 'ingestfileload')")
tables = [row[0] for row in cur.fetchall()]
print(f"Tables found: {tables}")

# Check columns on BatchUpload
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'batchupload' AND column_name IN ('scenario_key', 'scenario_generation')")
cols = [row[0] for row in cur.fetchall()]
print(f"BatchUpload scenario columns: {cols}")

cur.close()
conn.close()
