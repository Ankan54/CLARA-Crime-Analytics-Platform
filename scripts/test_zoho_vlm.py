"""Connectivity check for the Zoho-hosted Qwen3 VLM (image extraction).

Endpoint : https://api.catalyst.zoho.in/quickml/v1/project/<id>/vlm/chat
Headers  : Authorization: Zoho-oauthtoken <token>  (same OAuth refresh-token
           flow as ChatZohoGLM in backend/app/llm.py)
           CATALYST-ORG: <org_id>
Model    : VL-Qwen3.6-35B-A3B
Payload  : {"prompt", "model", "images": [base64 ...], "system_prompt",
            "top_k", "top_p", "temperature", "max_tokens"}

Builds a tiny synthetic PNG in pure stdlib (no Pillow dependency) — a solid
colour swatch — and asks the VLM to describe it, asserting a 2xx and a
non-empty response. This proves auth + endpoint + payload shape before the
image branch is wired into the ingestion pipeline.

Run: python scripts/test_zoho_vlm.py
"""
from __future__ import annotations

import base64
import os
import struct
import sys
import time
import zlib
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

_token_cache: dict[str, float | str | None] = {"token": None, "expires_at": 0.0}


def _get_access_token() -> str:
    now = time.time()
    token = _token_cache["token"]
    expires_at = float(_token_cache["expires_at"] or 0.0)
    if token and now < expires_at - 60:
        return str(token)

    resp = requests.post(
        f"{os.environ.get('ZOHO_CATALYST_AUTH_DOMAIN', 'https://accounts.zohoportal.in')}/oauth/v2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": os.environ["ZOHO_CATALYST_CLIENT_ID"],
            "client_secret": os.environ["ZOHO_CATALYST_CLIENT_SECRET"],
            "refresh_token": os.environ["ZOHO_CATALYST_REFRESH_TOKEN"],
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Token refresh failed: {data}")
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + float(data.get("expires_in", 3600))
    return str(data["access_token"])


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload))


def _make_test_png(width: int = 64, height: int = 64, rgb: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    """Solid-colour PNG built from raw stdlib (zlib deflate), no Pillow needed."""
    row = bytes([0]) + bytes(rgb) * width  # filter byte 0 (none) + RGB pixels
    raw = row * height
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # bit depth 8, color type 2 (RGB)
    idat = zlib.compress(raw, level=6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def test_vlm_connectivity() -> None:
    endpoint_url = os.environ.get("ZOHO_QUICKML_VLM_ENDPOINT_URL", "")
    catalyst_org = os.environ.get("ZOHO_QUICKML_CATALYST_ORG", "")
    model = os.environ.get("ZOHO_QUICKML_VLM_MODEL_NAME", "VL-Qwen3.6-35B-A3B")
    if not endpoint_url or not catalyst_org:
        raise SystemExit("Missing ZOHO_QUICKML_VLM_ENDPOINT_URL / ZOHO_QUICKML_CATALYST_ORG in .env")

    image_b64 = base64.b64encode(_make_test_png()).decode("ascii")
    payload = {
        "prompt": "Describe the dominant colour of this image in one word.",
        "model": model,
        "images": [image_b64],
        "system_prompt": "Be concise and factual.",
        "top_k": 50,
        "top_p": 0.9,
        "temperature": 0.2,
        "max_tokens": 50,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Zoho-oauthtoken {_get_access_token()}",
        "CATALYST-ORG": catalyst_org,
    }

    t0 = time.perf_counter()
    resp = requests.post(endpoint_url, json=payload, headers=headers, timeout=60)
    elapsed = (time.perf_counter() - t0) * 1000
    if resp.status_code != 200:
        raise RuntimeError(f"VLM API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    content = data.get("response") or data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not str(content).strip():
        raise RuntimeError(f"VLM returned an empty response: {data}")

    print(f"PASS  VLM {model} responded in {elapsed:.0f}ms")
    print(f"  -> {str(content)[:300]}")


if __name__ == "__main__":
    try:
        test_vlm_connectivity()
    except Exception as exc:
        print(f"FAIL  {exc}")
        sys.exit(1)
    sys.exit(0)
