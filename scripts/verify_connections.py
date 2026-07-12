"""One-shot connectivity check for ingestion dependencies. Run: python scripts/verify_connections.py"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# ponytail: zcatalyst-sdk defaults to localzoho.com; India DC needs these overrides.
os.environ.setdefault("X_ZOHO_CATALYST_ACCOUNTS_URL", "https://accounts.zoho.in")
os.environ.setdefault(
    "X_ZOHO_CATALYST_CONSOLE_URL",
    os.environ.get("ZOHO_CATALYST_PROJECT_DOMAIN", "https://api.catalyst.zoho.in"),
)
os.environ.setdefault("X_ZOHO_STRATUS_RESOURCE_SUFFIX", ".zohostratus.in")


def _patch_zcatalyst_url_join() -> None:
    """SDK joins accounts base + '/' + '/oauth/...' → double slash (404 on .in)."""
    from zcatalyst_sdk._http_client import HttpClient

    if getattr(HttpClient.request, "_ksp_patched", False):
        return
    _orig = HttpClient.request

    def _request(self, method, url=None, path=None, *args, **kwargs):
        # Only OAuth paths: baas/stratus paths need their leading slash for join.
        if url is None and path and str(path).startswith("/oauth"):
            path = path.lstrip("/")
        return _orig(self, method, url, path, *args, **kwargs)

    _request._ksp_patched = True  # type: ignore[attr-defined]
    HttpClient.request = _request  # type: ignore[method-assign]


_patch_zcatalyst_url_join()

results: list[tuple[str, str, str]] = []


def ok(name: str, detail: str = "") -> None:
    results.append(("PASS", name, detail))
    print(f"PASS  {name}" + (f": {detail}" if detail else ""), flush=True)


def fail(name: str, err: Exception | str) -> None:
    results.append(("FAIL", name, str(err)))
    print(f"FAIL  {name}: {err}", flush=True)


def _catalyst_credential():
    import zcatalyst_sdk
    from zcatalyst_sdk import credentials

    refresh_fields = {
        "refresh_token": os.environ["ZOHO_CATALYST_REFRESH_TOKEN"],
        "client_id": os.environ["ZOHO_CATALYST_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CATALYST_CLIENT_SECRET"],
    }
    access_token = os.environ.get("ZOHO_CATALYST_ACCESS_TOKEN", "").strip()
    try:
        cred = credentials.RefreshTokenCredential(refresh_fields)
        cred.token()
        return cred, "refresh_token"
    except Exception as refresh_err:
        if not access_token:
            raise refresh_err
        return credentials.AccessTokenCredential({"access_token": access_token}), "access_token"


def test_stratus() -> None:
    import zcatalyst_sdk
    from zcatalyst_sdk import types

    cred, cred_src = _catalyst_credential()
    options = types.ICatalystOptions(
        project_id=os.environ["ZOHO_CATALYST_PROJECT_ID"],
        project_key=os.environ["ZOHO_CATALYST_PROJECT_KEY"],
        environment=os.environ.get("ZOHO_CATALYST_ENVIRONMENT", "Development"),
        project_domain=os.environ["ZOHO_CATALYST_PROJECT_DOMAIN"],
    )
    app = zcatalyst_sdk.initialize_app(credential=cred, options=options)
    stratus = app.stratus()
    buckets = stratus.list_buckets()
    ok("Catalyst Stratus list_buckets", f"{cred_src}; {str(buckets)[:180]}")

    bucket_name = os.environ["ZOHO_STRATUS_BUCKET"]
    bucket = stratus.bucket(bucket_name)
    bucket.get_details()
    ok("Catalyst Stratus bucket access", bucket_name)

    test_key = "_ingest_test/connection_check.txt"
    bucket.put_object(test_key, b"ksp datathon stratus connection test")
    ok("Catalyst Stratus put_object", test_key)

    # The raw/processed/archive pipeline additionally needs list/rename/copy/delete,
    # which require broader (admin) bucket scopes than a plain put/get.
    page = bucket.list_paged_objects(prefix="_ingest_test/")
    keys = [obj.to_dict().get("key") if hasattr(obj, "to_dict") else obj.get("key") for obj in page["contents"]]
    if test_key not in keys:
        raise RuntimeError(f"list_paged_objects did not return {test_key}: {keys}")
    ok("Catalyst Stratus list_paged_objects", f"{len(keys)} object(s)")

    moved_key = "_ingest_test/connection_check_moved.txt"
    try:
        bucket.rename_object(test_key, moved_key)
        ok("Catalyst Stratus rename_object", f"{test_key} -> {moved_key}")
    except Exception as rename_err:
        bucket.copy_object(test_key, moved_key)
        bucket.delete_object(test_key)
        ok("Catalyst Stratus copy_object+delete_object (rename_object fallback)", str(rename_err)[:120])

    bucket.delete_object(moved_key)
    ok("Catalyst Stratus delete_object", moved_key)


def test_neo4j() -> None:
    from neo4j import GraphDatabase

    uri = os.environ["NEO4J_URI"]
    password = os.environ["NEO4J_PASSWORD"]
    last_err: Exception | None = None
    for user in dict.fromkeys([os.environ.get("NEO4J_USERNAME", "neo4j"), "neo4j"]):
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            driver.close()
            ok("Neo4j Aura verify_connectivity", f"user={user}")
            return
        except Exception as e:
            last_err = e
    raise last_err or RuntimeError("Neo4j auth failed")


def test_pinecone() -> None:
    from pinecone import Pinecone

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    names = pc.list_indexes().names()
    ok("Pinecone list_indexes", f"{len(names)} index(es): {list(names)}")


def test_bedrock() -> None:
    import boto3

    client = boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )
    body = json.dumps({"inputText": "ksp ingestion smoke test"})
    resp = client.invoke_model(
        modelId=os.environ["BEDROCK_EMBEDDING_MODEL"],
        body=body,
        accept="application/json",
        contentType="application/json",
    )
    emb = json.loads(resp["body"].read()).get("embedding", [])
    if len(emb) != 1536:
        raise ValueError(f"expected 1536-d embedding, got {len(emb)}")
    ok("Bedrock Titan embedding", f"dim={len(emb)}")


def main() -> int:
    for name, fn in [
        ("Catalyst Stratus", test_stratus),
        ("Neo4j Aura", test_neo4j),
        ("Pinecone", test_pinecone),
        ("Bedrock Titan", test_bedrock),
    ]:
        print(f"\n--- {name} ---", flush=True)
        try:
            fn()
        except Exception as e:
            fail(name, e)

    fails = [r for r in results if r[0] == "FAIL"]
    print(f"\nSummary: {len(results) - len(fails)}/{len(results)} passed", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
