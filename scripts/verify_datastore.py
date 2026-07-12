"""
Catalyst DataStore connection check.
Creates a test table row, queries it with ZCQL, then cleans up.

PREREQUISITE: Create a table called 'KSP_Test' in the Catalyst console with these columns:
  - case_id   (Text / Single-line)
  - summary   (Text / Multi-line)
  - score     (Number)

Run: python scripts/verify_datastore.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# India DC overrides — must be before zcatalyst_sdk import
os.environ.setdefault("X_ZOHO_CATALYST_ACCOUNTS_URL", "https://accounts.zoho.in")
os.environ.setdefault(
    "X_ZOHO_CATALYST_CONSOLE_URL",
    os.environ.get("ZOHO_CATALYST_PROJECT_DOMAIN", "https://api.catalyst.zoho.in"),
)
os.environ.setdefault("X_ZOHO_STRATUS_RESOURCE_SUFFIX", ".zohostratus.in")


def _patch_sdk() -> None:
    from zcatalyst_sdk._http_client import HttpClient
    if getattr(HttpClient.request, "_ksp_patched", False):
        return
    _orig = HttpClient.request
    def _req(self, method, url=None, path=None, *args, **kwargs):
        if url is None and path and str(path).startswith("/oauth"):
            path = path.lstrip("/")
        return _orig(self, method, url, path, *args, **kwargs)
    _req._ksp_patched = True  # type: ignore[attr-defined]
    HttpClient.request = _req  # type: ignore[method-assign]

_patch_sdk()

import zcatalyst_sdk
from zcatalyst_sdk import credentials, types

TEST_TABLE = os.environ.get("ZOHO_DATASTORE_TEST_TABLE", "KSP_Test")

def _app():
    cred = credentials.RefreshTokenCredential({
        "refresh_token": os.environ["ZOHO_CATALYST_REFRESH_TOKEN_DS"],
        "client_id":     os.environ["ZOHO_CATALYST_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CATALYST_CLIENT_SECRET"],
    })
    opts = types.ICatalystOptions(
        project_id=os.environ["ZOHO_CATALYST_PROJECT_ID"],
        project_key=os.environ["ZOHO_CATALYST_PROJECT_KEY"],
        environment=os.environ.get("ZOHO_CATALYST_ENVIRONMENT", "Development"),
        project_domain=os.environ["ZOHO_CATALYST_PROJECT_DOMAIN"],
    )
    return zcatalyst_sdk.initialize_app(credential=cred, options=opts, name="ksp-ds-test")


def main() -> int:
    # ---------- 1. list tables ----------
    app = _app()
    ds = app.datastore()
    tables = ds.get_all_tables()
    names = [t.to_dict().get("table_name") for t in tables]
    print(f"PASS  list_tables: {names}")

    if TEST_TABLE not in names:
        print(
            f"\nSKIP  '{TEST_TABLE}' table not found in DataStore.\n"
            "      Create it in the Catalyst console (Cloud Scale → Data Store → New Table)\n"
            "      with columns: case_id (Text), summary (Text), score (Number)\n"
            f"      or set ZOHO_DATASTORE_TEST_TABLE to one of: {names}"
        )
        return 0

    table = ds.table(TEST_TABLE)

    # ---------- 2. insert a row ----------
    inserted = table.insert_row({
        "case_id": "KSP_CONN_TEST",
        "summary": "DataStore connectivity check",
        "score": 99,
    })
    row_id = inserted[TEST_TABLE]["ROWID"]
    print(f"PASS  insert_row: ROWID={row_id}")

    # ---------- 3. ZCQL SELECT ----------
    zcql = app.zcql()
    result = zcql.execute_query(
        f"SELECT case_id, summary, score FROM {TEST_TABLE} WHERE ROWID = {row_id}"
    )
    row = result[0][TEST_TABLE]
    assert row["case_id"] == "KSP_CONN_TEST", f"unexpected: {row}"
    print(f"PASS  zcql_select: {row}")

    # ---------- 4. cleanup ----------
    table.delete_row(row_id)
    print(f"PASS  delete_row: ROWID={row_id} cleaned up")

    print("\nSummary: DataStore + ZCQL fully operational.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
