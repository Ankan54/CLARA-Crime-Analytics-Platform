from dotenv import load_dotenv; load_dotenv()
import os, psycopg2

conn = psycopg2.connect(
    host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
    dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"], sslmode="require"
)
cur = conn.cursor()
cur.execute(
    "SELECT table_schema, table_name FROM information_schema.tables "
    "WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema') "
    "ORDER BY table_schema, table_name"
)
rows = cur.fetchall()
print(f"Total tables: {len(rows)}")
for s, n in rows:
    print(f"  {s}.{n}")
cur.execute("SHOW search_path")
print("search_path:", cur.fetchone())
conn.close()
