"""Try submitting via zcatalyst_sdk job_scheduling instead of REST."""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parents[1] / ".env", override=True)
import os, sys

os.environ.setdefault("X_ZOHO_CATALYST_ACCOUNTS_URL", os.environ.get("ZOHO_CATALYST_AUTH_DOMAIN", "https://accounts.zohoportal.in"))
os.environ.setdefault("X_ZOHO_CATALYST_CONSOLE_URL", os.environ.get("ZOHO_CATALYST_PROJECT_DOMAIN", "https://api.catalyst.zoho.in"))
os.environ.setdefault("X_ZOHO_STRATUS_RESOURCE_SUFFIX", ".zohostratus.in")

from zcatalyst_sdk._http_client import HttpClient
if not getattr(HttpClient.request, "_ksp_patched", False):
    _orig = HttpClient.request
    def _req(self, method, url=None, path=None, *a, **kw):
        if url is None and path and str(path).startswith("/oauth"):
            path = path.lstrip("/")
        return _orig(self, method, url, path, *a, **kw)
    _req._ksp_patched = True
    HttpClient.request = _req

import zcatalyst_sdk
from zcatalyst_sdk import credentials, types

cred = credentials.RefreshTokenCredential({
    "refresh_token": os.environ["ZOHO_CATALYST_REFRESH_TOKEN"],
    "client_id": os.environ["ZOHO_CATALYST_CLIENT_ID"],
    "client_secret": os.environ["ZOHO_CATALYST_CLIENT_SECRET"],
})
opts = types.ICatalystOptions(
    project_id=os.environ["ZOHO_CATALYST_PROJECT_ID"],
    project_key=os.environ["ZOHO_CATALYST_PROJECT_KEY"],
    environment=os.environ.get("ZOHO_CATALYST_ENVIRONMENT", "Development"),
    project_domain=os.environ["ZOHO_CATALYST_PROJECT_DOMAIN"],
)
app = zcatalyst_sdk.initialize_app(credential=cred, options=opts)

RUN_ID  = sys.argv[1] if len(sys.argv) > 1 else "TEST_RUN_SDK"
BATCH   = sys.argv[2] if len(sys.argv) > 2 else "00000000-0000-0000-0000-000000000000"
CASE_ID = sys.argv[3] if len(sys.argv) > 3 else "1000063"

job_meta = {
    "job_name": f"test_{RUN_ID}"[:20],  # Catalyst: alphanumeric + underscore, 1-20 chars
    "jobpool_name": "ingestpool",
    "jobpool_id": "42220000000026052",
    "target_type": "Function",
    "target_name": "ingest_processor",
    "target_id": "42220000000026012",
    "params": {"run_id": RUN_ID, "batch_id": BATCH, "case_id": CASE_ID, "phase": "extract"},
    "job_config": {"number_of_retries": 0, "retry_interval": 300},
}
print("Submitting via SDK...")
try:
    result = app.job_scheduling().job.submit_job(job_meta)
    print("SDK result:", result)
except Exception as exc:
    print("SDK error:", exc)
