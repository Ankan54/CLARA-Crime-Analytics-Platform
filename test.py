"""
Test: Pinecone search + Stratus text retrieval with latency measurement.
"""
import os, json, time, boto3
from pinecone import Pinecone
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Stratus setup (India DC patches)
# ---------------------------------------------------------------------------
os.environ.setdefault("X_ZOHO_CATALYST_ACCOUNTS_URL", "https://accounts.zoho.in")
os.environ.setdefault("X_ZOHO_CATALYST_CONSOLE_URL", os.environ.get("ZOHO_CATALYST_PROJECT_DOMAIN", "https://api.catalyst.zoho.in"))
os.environ.setdefault("X_ZOHO_STRATUS_RESOURCE_SUFFIX", ".zohostratus.in")

def _patch_zcatalyst():
    from zcatalyst_sdk._http_client import HttpClient
    if getattr(HttpClient.request, "_ksp_patched", False):
        return
    _orig = HttpClient.request
    def _req(self, method, url=None, path=None, *args, **kwargs):
        if url is None and path and str(path).startswith("/oauth"):
            path = path.lstrip("/")
        return _orig(self, method, url, path, *args, **kwargs)
    _req._ksp_patched = True
    HttpClient.request = _req

_patch_zcatalyst()

def _init_stratus_bucket():
    import zcatalyst_sdk
    from zcatalyst_sdk import credentials, types
    try:
        app = zcatalyst_sdk.get_app()
    except Exception:
        cred = credentials.RefreshTokenCredential({
            "refresh_token": os.environ["ZOHO_CATALYST_REFRESH_TOKEN"],
            "client_id":     os.environ["ZOHO_CATALYST_CLIENT_ID"],
            "client_secret": os.environ["ZOHO_CATALYST_CLIENT_SECRET"],
        })
        options = types.ICatalystOptions(
            project_id=os.environ["ZOHO_CATALYST_PROJECT_ID"],
            project_key=os.environ["ZOHO_CATALYST_PROJECT_KEY"],
            environment=os.environ.get("ZOHO_CATALYST_ENVIRONMENT", "Development"),
            project_domain=os.environ["ZOHO_CATALYST_PROJECT_DOMAIN"],
        )
        app = zcatalyst_sdk.initialize_app(credential=cred, options=options)
    return app.stratus().bucket(os.environ["ZOHO_STRATUS_BUCKET"])

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
pc      = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index   = pc.Index("ksp-crime-intel")
bucket  = _init_stratus_bucket()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def embed(text: str) -> list:
    resp = bedrock.invoke_model(
        modelId="amazon.titan-embed-text-v1",
        body=json.dumps({"inputText": text[:40000]}),
        accept="application/json", contentType="application/json",
    )
    return json.loads(resp["body"].read())["embedding"]

def fetch_from_stratus(blob_uri: str) -> str:
    """Fetch full text given stratus://ksp-data-files/<key>."""
    key = blob_uri.split("stratus://ksp-data-files/")[-1]
    raw = bucket.get_object(key)
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

# ---------------------------------------------------------------------------
# Main: search + retrieve
# ---------------------------------------------------------------------------
def search_and_retrieve(query: str, top_k: int = 3, filters: dict = None):
    sep = "=" * 70

    print(f"\n{sep}")
    print(f"Query : {query}")
    if filters:
        print(f"Filter: {filters}")
    print(sep)

    # Step 1: embed + search
    t0 = time.perf_counter()
    vec = embed(query)
    t_embed = time.perf_counter() - t0

    t1 = time.perf_counter()
    results = index.query(vector=vec, top_k=top_k, include_metadata=True, filter=filters)
    t_search = time.perf_counter() - t1

    matches = results["matches"]
    print(f"\nEmbed: {t_embed*1000:.0f}ms   Pinecone search: {t_search*1000:.0f}ms   ({len(matches)} results)")

    # Step 2: fetch full text from Stratus
    for i, m in enumerate(matches, 1):
        meta = m["metadata"]
        blob_uri = meta.get("blob_uri", "")

        t2 = time.perf_counter()
        text = fetch_from_stratus(blob_uri) if blob_uri else "[no blob_uri]"
        t_fetch = time.perf_counter() - t2

        print(f"\n{'─'*70}")
        print(f"#{i}  id={m['id']}  score={m['score']:.3f}  type={meta.get('doc_type')}")
        print(f"    crime={meta.get('crime_type')}  district={meta.get('district')}  status={meta.get('case_status')}  amount={meta.get('amount_band')}")
        print(f"    Stratus fetch: {t_fetch*1000:.0f}ms  |  uri={blob_uri}")
        print(f"\n{text[:1500]}{'...(truncated)' if len(text) > 1500 else ''}")

    total = (time.perf_counter() - t0) * 1000
    print(f"\n{'─'*70}")
    print(f"Total end-to-end: {total:.0f}ms  (embed {t_embed*1000:.0f}ms + search {t_search*1000:.0f}ms + {len(matches)}x Stratus fetches)")

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    search_and_retrieve(
        "victim received call from fake CBI officer claiming digital arrest, transferred money under duress",
        top_k=3,
    )
