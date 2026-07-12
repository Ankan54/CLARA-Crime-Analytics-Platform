"""
blob_store.py — Upload historical docs + evidence to Zoho Stratus (overwrite semantics).
Writes .ingest_checkpoints/blob_manifest.json: {local_path -> stratus_uri}.
Single app instance to avoid repeated OAuth refreshes hitting rate limits.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from . import config as cfg

# ---------------------------------------------------------------------------
# India DC overrides — must be set before zcatalyst_sdk import
# ponytail: same patches as verify_connections.py; centralised here so
# preflight.py's import already sets them, but idempotent if called standalone.
# ---------------------------------------------------------------------------
os.environ.setdefault("X_ZOHO_CATALYST_ACCOUNTS_URL", "https://accounts.zoho.in")
os.environ.setdefault("X_ZOHO_CATALYST_CONSOLE_URL", cfg.ZOHO_PROJECT_DOMAIN)
os.environ.setdefault("X_ZOHO_STRATUS_RESOURCE_SUFFIX", ".zohostratus.in")


def _patch_zcatalyst_url_join() -> None:
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


def _get_credential():
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
        return cred
    except Exception:
        if access_token:
            return credentials.AccessTokenCredential({"access_token": access_token})
        raise


def _init_app():
    _patch_zcatalyst_url_join()
    import zcatalyst_sdk
    from zcatalyst_sdk import types

    # SDK enforces a singleton — reuse existing app if preflight already initialised it.
    try:
        return zcatalyst_sdk.get_app()
    except Exception:
        pass

    cred = _get_credential()
    options = types.ICatalystOptions(
        project_id=cfg.ZOHO_PROJECT_ID,
        project_key=cfg.ZOHO_PROJECT_KEY,
        environment=cfg.ZOHO_ENVIRONMENT,
        project_domain=cfg.ZOHO_PROJECT_DOMAIN,
    )
    return zcatalyst_sdk.initialize_app(credential=cred, options=options)


def _stratus_key(local_path: Path) -> str:
    """Map local path to deterministic Stratus key under historical/."""
    try:
        rel = local_path.relative_to(cfg.DOCS_DIR.parent)
    except ValueError:
        rel = local_path.name  # type: ignore[assignment]
    return f"historical/{str(rel).replace(chr(92), '/')}"


def _stratus_uri(key: str) -> str:
    return f"stratus://{cfg.ZOHO_STRATUS_BUCKET}/{key}"


def run() -> dict[str, str]:
    """
    Upload all docs + evidence files.
    Returns manifest: {str(local_path): stratus_uri}.
    Writes blob_manifest.json to STATE_DIR.
    """
    print("[blob_store] Scanning source files …", flush=True)

    files: list[Path] = []
    # Only historical/docs/ — evidence lives in live_demo/ and is loaded during demo only
    if cfg.DOCS_DIR.exists():
        files.extend(p for p in cfg.DOCS_DIR.rglob("*") if p.is_file())

    if not files:
        print("[blob_store] WARNING: no files found in docs/", flush=True)

    app = _init_app()
    bucket = app.stratus().bucket(cfg.ZOHO_STRATUS_BUCKET)

    manifest: dict[str, str] = {}
    for i, fpath in enumerate(sorted(files), 1):
        key = _stratus_key(fpath)
        uri = _stratus_uri(key)
        data = fpath.read_bytes()
        bucket.put_object(key, data, options={"overwrite": "true"})
        manifest[str(fpath)] = uri
        if i % 10 == 0 or i == len(files):
            print(f"[blob_store] {i}/{len(files)} uploaded", flush=True)

    cfg.STATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg.BLOB_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[blob_store] Manifest written -> {cfg.BLOB_MANIFEST} ({len(manifest)} entries)", flush=True)
    return manifest
