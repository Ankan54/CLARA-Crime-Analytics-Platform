"""
vector_store.py — Pinecone wipe + embed + upsert with rich metadata.

Flow:
  1. Create index if absent (serverless, aws/us-east-1, 1536-d cosine)
  2. Wipe (delete_all=True) unless --no-wipe
  3. For each narratives.jsonl record:
       - resolve case_master_id
       - embed text
       - merge: JSONL base (strip lat/lon/pincode/district_id) + case_enrich[cm_id]
         + amount_band + blob_uri (from manifest)
       - sanitize: only str/int/float/bool/list[str]; drop None values
  4. Batch upsert (100)
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

from . import config as cfg
from .case_enrich import build as build_enrich
from .embeddings import embed

# Fields in the JSONL metadata that are superseded by case_enrich or explicitly dropped.
_DROP_JSONL_FIELDS = {"latitude", "longitude", "pincode", "district_id", "lang"}


def _sanitize(meta: dict[str, Any]) -> dict[str, Any]:
    """
    Pinecone metadata constraints: str | int | float | bool | list[str] only.
    Drop None values and non-conforming types.
    """
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = v
        elif isinstance(v, str):
            out[k] = v
        elif isinstance(v, list):
            # coerce to list[str], drop empties
            lst = [str(x) for x in v if x is not None]
            if lst:
                out[k] = lst
        # anything else (dict, etc.) is silently dropped
    return out


def _load_manifest() -> dict[str, str]:
    """Returns {str(local_path): stratus_uri} or {} if not yet written."""
    if cfg.BLOB_MANIFEST.exists():
        return json.loads(cfg.BLOB_MANIFEST.read_text(encoding="utf-8"))
    return {}


def _crime_no_to_blob_uri(crime_no: str, doc_type: str, manifest: dict[str, str]) -> str:
    """Resolve deterministic Stratus URI for a given CrimeNo + doc_type."""
    # blob_store uses key: historical/docs/<CrimeNo>/<fir|investigation_report>.txt
    fname = "fir.txt" if doc_type == "fir" else "investigation_report.txt"
    key = f"historical/docs/{crime_no}/{fname}"
    # scan manifest for matching key suffix
    for uri in manifest.values():
        if uri.endswith(key):
            return uri
    # best-effort fallback
    return f"stratus://{cfg.ZOHO_STRATUS_BUCKET}/{key}"


def _get_or_create_index():
    from pinecone import Pinecone, ServerlessSpec

    pc = Pinecone(api_key=__import__("os").environ["PINECONE_API_KEY"])
    existing = pc.list_indexes().names()
    if cfg.PINECONE_INDEX not in existing:
        print(f"[vector_store] Creating Pinecone index '{cfg.PINECONE_INDEX}' …", flush=True)
        pc.create_index(
            name=cfg.PINECONE_INDEX,
            dimension=cfg.PINECONE_DIM,
            metric=cfg.PINECONE_METRIC,
            spec=ServerlessSpec(cloud=cfg.PINECONE_CLOUD, region=cfg.PINECONE_REGION),
        )
        # Poll until ready
        for _ in range(30):
            desc = pc.describe_index(cfg.PINECONE_INDEX)
            if desc.status.get("ready", False):
                break
            time.sleep(5)
    return pc.Index(cfg.PINECONE_INDEX)


def run(wipe: bool = True) -> None:
    """Embed and upsert all 93 narratives with rich metadata."""
    print("[vector_store] Initialising Pinecone index …", flush=True)
    index = _get_or_create_index()

    if wipe:
        print("[vector_store] Wiping existing vectors …", flush=True)
        stats = index.describe_index_stats()
        if stats.total_vector_count > 0:
            index.delete(delete_all=True)
            time.sleep(2)  # brief settle after delete
        else:
            print("[vector_store] Index is already empty, skipping delete", flush=True)

    manifest = _load_manifest()
    enriched = build_enrich()

    records = []
    with open(cfg.NARRATIVES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"[vector_store] Embedding {len(records)} records …", flush=True)
    vectors = []

    for i, rec in enumerate(records, 1):
        node_id = rec["node_id"]
        doc_type = rec.get("doc_type", "fir")
        base_meta = rec.get("metadata", {})

        # Resolve CaseMasterID
        if doc_type == "fir":
            cm_id = int(node_id)
        else:
            cm_id = int(base_meta.get("case_master_id", 0))

        # Embed
        vector = embed(rec["text"])

        # Build metadata: start from case_enrich (authoritative)
        meta: dict[str, Any] = {}
        if cm_id in enriched:
            meta.update(enriched[cm_id])

        # Layer JSONL base fields (excluding dropped ones and those already in enrich)
        for k, v in base_meta.items():
            if k not in _DROP_JSONL_FIELDS and k not in meta:
                meta[k] = v

        # FIR-specific: keep JSONL crime_type (already in enrich; JSONL may have
        # a more specific code e.g. "digital_arrest" while enrich derives via subhead)
        # JSONL wins only for FIRs where it was explicitly set at generation time.
        if doc_type == "fir" and base_meta.get("crime_type"):
            meta["crime_type"] = base_meta["crime_type"]

        # amount_band: re-derive from enriched amount_involved if available
        if meta.get("amount_involved") is None and base_meta.get("amount_involved"):
            meta["amount_involved"] = base_meta["amount_involved"]
        if meta.get("amount_involved") is not None:
            meta["amount_band"] = cfg.amount_band(meta["amount_involved"])

        # blob_uri
        crime_no = base_meta.get("CrimeNo") or meta.get("crime_no", "")
        meta["blob_uri"] = _crime_no_to_blob_uri(crime_no, doc_type, manifest)

        # node_id always string
        meta["node_id"] = str(node_id)

        # Sanitize
        meta = _sanitize(meta)

        vectors.append({"id": str(node_id), "values": vector, "metadata": meta})

        if i % 10 == 0 or i == len(records):
            print(f"[vector_store] Embedded {i}/{len(records)}", flush=True)

    # Batch upsert
    print(f"[vector_store] Upserting {len(vectors)} vectors …", flush=True)
    for start in range(0, len(vectors), cfg.PINECONE_BATCH):
        batch = vectors[start: start + cfg.PINECONE_BATCH]
        index.upsert(vectors=batch)

    # Verify count
    time.sleep(3)
    stats = index.describe_index_stats()
    total = stats.total_vector_count
    print(f"[vector_store] Done. Index now has {total} vectors.", flush=True)
