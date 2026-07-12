"""List all Stratus objects under historical/ and delete any stale evidence keys."""
import os
from dotenv import load_dotenv; load_dotenv()

os.environ.setdefault("X_ZOHO_CATALYST_ACCOUNTS_URL", "https://accounts.zohoportal.in")
os.environ.setdefault("X_ZOHO_CATALYST_CONSOLE_URL", os.environ["ZOHO_CATALYST_PROJECT_DOMAIN"])
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
try:
    app = zcatalyst_sdk.get_app()
except Exception:
    app = zcatalyst_sdk.initialize_app(credential=cred, options=types.ICatalystOptions(
        project_id=os.environ["ZOHO_CATALYST_PROJECT_ID"],
        project_key=os.environ["ZOHO_CATALYST_PROJECT_KEY"],
        environment=os.environ["ZOHO_CATALYST_ENVIRONMENT"],
        project_domain=os.environ["ZOHO_CATALYST_PROJECT_DOMAIN"],
    ))

bucket = app.stratus().bucket(os.environ["ZOHO_STRATUS_BUCKET"])

# Collect all keys using list_iterable_objects
all_keys = []
for obj in bucket.list_iterable_objects(prefix="historical/"):
    # StratusObject uses object_details dict or to_dict()
    details = obj.to_dict() if hasattr(obj, "to_dict") else {}
    key = details.get("key") or details.get("Key") or details.get("object_key") or details.get("name")
    if key is None and not all_keys:
        print("to_dict() sample:", details)
        break
    if key:
        all_keys.append(key)

docs_keys = [k for k in all_keys if "/docs/" in k]
evidence_keys = [k for k in all_keys if "/evidence/" in k]

print(f"Total in Stratus historical/: {len(all_keys)}")
print(f"  docs/: {len(docs_keys)}")
print(f"  evidence/: {len(evidence_keys)}")

if evidence_keys:
    print()
    print("Stale evidence keys in Stratus (should NOT be there):")
    for k in sorted(evidence_keys):
        print(f"  {k}")
    print()
    print(f"Deleting {len(evidence_keys)} stale evidence files from Stratus …")
    for k in evidence_keys:
        bucket.delete_object(k)
        print(f"  DELETED {k}")
    print("Done — Stratus historical/evidence/ is now clean.")
else:
    print()
    print("No evidence keys in Stratus — clean.")
