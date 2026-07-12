"""
preflight.py — Gates the pipeline before any wipe.
Checks: env vars, source files, Bedrock 1536-d, Neo4j, Pinecone, Stratus bucket.
Raises SystemExit(1) on any failure so the orchestrator can stop safely.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

from . import config as cfg

# ---------------------------------------------------------------------------
# India DC SDK patches — must happen before zcatalyst_sdk is imported
# ---------------------------------------------------------------------------
os.environ.setdefault("X_ZOHO_CATALYST_ACCOUNTS_URL", "https://accounts.zoho.in")
os.environ.setdefault("X_ZOHO_CATALYST_CONSOLE_URL", cfg.ZOHO_PROJECT_DOMAIN)
os.environ.setdefault("X_ZOHO_STRATUS_RESOURCE_SUFFIX", ".zohostratus.in")


def _patch_zcatalyst_url_join() -> None:
    """SDK joins accounts base + '/' + '/oauth/...' → double slash (404 on .in)."""
    from zcatalyst_sdk._http_client import HttpClient
    if getattr(HttpClient.request, "_ksp_patched", False):
        return
    _orig = HttpClient.request

    def _request(self, method, url=None, path=None, *args, **kwargs):
        if url is None and path and str(path).startswith("/oauth"):
            path = path.lstrip("/")
        return _orig(self, method, url, path, *args, **kwargs)

    _request._ksp_patched = True  # type: ignore[attr-defined]
    HttpClient.request = _request  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
_failures: list[str] = []


def _ok(label: str, detail: str = "") -> None:
    print(f"  PASS  {label}" + (f" — {detail}" if detail else ""), flush=True)


def _fail(label: str, reason: str) -> None:
    _failures.append(f"{label}: {reason}")
    print(f"  FAIL  {label} — {reason}", flush=True)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
def _check_env() -> None:
    missing = [k for k in cfg.REQUIRED_ENV_VARS if not os.getenv(k)]
    if missing:
        _fail("env vars", f"missing: {missing}")
    else:
        _ok("env vars")


def _check_source_files() -> None:
    required = [
        cfg.NARRATIVES_PATH,
        cfg.SCHEMA_PATH,
        cfg.SQL_DIR / "ksp",
        cfg.GRAPH_DIR,
    ]
    for p in required:
        if not p.exists():
            _fail(f"source path", str(p))
        else:
            _ok(f"source path", str(p.name))


def _check_bedrock() -> None:
    import boto3
    import botocore.exceptions

    client = boto3.client("bedrock-runtime", region_name=cfg.AWS_REGION)
    body = json.dumps({"inputText": "ksp ingestion preflight"})
    try:
        resp = client.invoke_model(
            modelId=cfg.BEDROCK_EMBEDDING_MODEL,
            body=body,
            accept="application/json",
            contentType="application/json",
        )
        emb = json.loads(resp["body"].read()).get("embedding", [])
        if len(emb) != cfg.PINECONE_DIM:
            _fail("Bedrock Titan", f"expected {cfg.PINECONE_DIM}-d, got {len(emb)}")
        else:
            _ok("Bedrock Titan", f"dim={len(emb)}")
    except botocore.exceptions.ClientError as e:
        _fail("Bedrock Titan", str(e))


def _check_neo4j() -> None:
    from neo4j import GraphDatabase

    uri, password = cfg.NEO4J_URI, cfg.NEO4J_PASSWORD
    for user in dict.fromkeys([cfg.NEO4J_USERNAME, "neo4j"]):
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            driver.close()
            _ok("Neo4j Aura", f"user={user}")
            return
        except Exception:
            pass
    _fail("Neo4j Aura", "connectivity check failed — check URI/credentials")


def _check_pinecone() -> None:
    from pinecone import Pinecone

    try:
        pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        names = pc.list_indexes().names()
        _ok("Pinecone", f"list_indexes OK ({len(names)} existing)")
    except Exception as e:
        _fail("Pinecone", str(e))


def _get_catalyst_credential():
    """Returns (cred, source_label). Falls back to access token if refresh fails."""
    from zcatalyst_sdk import credentials

    refresh_fields = {
        "refresh_token": cfg.ZOHO_REFRESH_TOKEN,
        "client_id": cfg.ZOHO_CLIENT_ID,
        "client_secret": cfg.ZOHO_CLIENT_SECRET,
    }
    access_token = os.getenv("ZOHO_CATALYST_ACCESS_TOKEN", "").strip()
    try:
        cred = credentials.RefreshTokenCredential(refresh_fields)
        cred.token()
        return cred, "refresh_token"
    except Exception as e:
        if access_token:
            return credentials.AccessTokenCredential({"access_token": access_token}), "access_token"
        raise


def _check_postgres() -> None:
    import psycopg2

    try:
        conn = psycopg2.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            sslmode=os.environ.get("DB_SSL", "require"),
            connect_timeout=10,
        )
        conn.close()
        _ok("Postgres RDS", f"{os.environ['DB_HOST']}")
    except Exception as e:
        _fail("Postgres RDS", str(e))


def _check_stratus() -> None:
    _patch_zcatalyst_url_join()
    import zcatalyst_sdk
    from zcatalyst_sdk import types

    try:
        # Reuse existing app if already initialised (e.g. called twice in same process)
        try:
            app = zcatalyst_sdk.get_app()
        except Exception:
            cred, src = _get_catalyst_credential()
            options = types.ICatalystOptions(
                project_id=cfg.ZOHO_PROJECT_ID,
                project_key=cfg.ZOHO_PROJECT_KEY,
                environment=cfg.ZOHO_ENVIRONMENT,
                project_domain=cfg.ZOHO_PROJECT_DOMAIN,
            )
            app = zcatalyst_sdk.initialize_app(credential=cred, options=options)
            src = src  # noqa: F841 — used only for the log message below
        bucket = app.stratus().bucket(cfg.ZOHO_STRATUS_BUCKET)
        bucket.get_details()
        _ok("Zoho Stratus", f"{cfg.ZOHO_STRATUS_BUCKET} accessible")
    except Exception as e:
        _fail("Zoho Stratus", str(e))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run(skip_stratus: bool = False) -> None:
    """Run all preflight checks. Raises SystemExit(1) if any fail."""
    print("[preflight] Checking environment and connectivity …", flush=True)

    _check_env()
    _check_source_files()
    _check_bedrock()
    _check_neo4j()
    _check_pinecone()
    _check_postgres()
    if not skip_stratus:
        _check_stratus()

    if _failures:
        print(f"\n[preflight] FAILED — {len(_failures)} issue(s):", flush=True)
        for f in _failures:
            print(f"  • {f}", flush=True)
        sys.exit(1)
    print("[preflight] All checks PASSED", flush=True)
