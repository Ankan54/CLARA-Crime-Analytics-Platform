"""Apply schema_pg.sql and seed_schema_config.sql to Supabase."""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parents[1] / ".env", override=True)
import os, psycopg

ROOT = Path(__file__).parents[1]
SCHEMA_SQL = ROOT / "backend" / "migrations" / "schema_pg.sql"
SEED_SQL = ROOT / "backend" / "migrations" / "seed_schema_config.sql"

pw = os.environ["DB_PASSWORD"].strip('"\'')
url = "postgresql://{}:{}@{}:{}/{}?sslmode={}".format(
    os.environ["DB_USER"], pw, os.environ["DB_HOST"],
    os.environ["DB_PORT"], os.environ["DB_NAME"], os.environ["DB_SSL"]
)
conn = psycopg.connect(url, prepare_threshold=0, autocommit=False)

for sql_file in [SCHEMA_SQL, SEED_SQL]:
    if not sql_file.exists():
        print(f"SKIP (not found): {sql_file}")
        continue
    print(f"Applying: {sql_file.name} ...")
    sql = sql_file.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
    ok = err = 0
    for stmt in statements:
        try:
            conn.execute(stmt)
            conn.commit()
            ok += 1
        except Exception as exc:
            conn.rollback()
            err += 1
            print(f"  WARN: {str(exc)[:150]}")
    print(f"  {sql_file.name}: {ok} ok, {err} errors")

conn.close()
print("Done.")
