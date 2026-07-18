"""
load_pinecone_from_historical.py — Embed and upsert historical FIR/IR
narratives into the live Pinecone index, so historical documents are findable
via semantic search alongside live-ingested ones (previously: nothing pushed
sample_data/historical/vector/narratives.jsonl anywhere -- it just sat on
disk. Confirmed via repo-wide search this session: no such loader existed).

Uses the same embedding model as live ingestion
(catalyst_functions/ingest_processor/pipeline/processor.py::_load_vector,
amazon.titan-embed-text-v1) and a metadata shape matching the live convention
(case_id, doc_type, origin, source) so the two are indistinguishable to a
downstream query except for origin.

Idempotent: vector ids are deterministic (historical::{node_id}::{doc_type}),
so re-running overwrites in place rather than duplicating.

Usage:
    python backend/migrations/load_pinecone_from_historical.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import boto3
from dotenv import load_dotenv
from pinecone import Pinecone

ROOT = Path(__file__).resolve().parents[2]
NARRATIVES_PATH = ROOT / "sample_data" / "historical" / "vector" / "narratives.jsonl"

BATCH_SIZE = 100

_DOC_TYPE_MAP = {"fir": "FIR", "ir": "IR"}


def _embed(text: str, bedrock) -> list[float]:
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    model = os.environ.get("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v1")
    resp = bedrock.invoke_model(modelId=model, body=json.dumps({"inputText": text[:40000]}))
    return json.loads(resp["body"].read().decode("utf-8"))["embedding"]


def load() -> None:
    load_dotenv(ROOT / ".env")

    if not NARRATIVES_PATH.exists():
        raise SystemExit(f"[pinecone-load] narratives.jsonl not found at {NARRATIVES_PATH}")

    with open(NARRATIVES_PATH, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    print(f"[pinecone-load] Read {len(records)} records from {NARRATIVES_PATH.relative_to(ROOT)}")

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    bedrock = boto3.client("bedrock-runtime", region_name=region)

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(os.environ.get("PINECONE_INDEX", "ksp-crime-intel"))

    vectors = []
    skipped = 0
    for rec in records:
        text = rec.get("text") or ""
        if not text.strip():
            skipped += 1
            continue
        doc_type = _DOC_TYPE_MAP.get((rec.get("doc_type") or "").lower(), (rec.get("doc_type") or "").upper())
        node_id = rec.get("node_id")
        meta = rec.get("metadata") or {}
        # FIR records: node_id IS the CaseMasterID (a plain int). IR records:
        # node_id is "IR:5000001" (the report's own id) -- the actual case is in
        # metadata.case_master_id. Using node_id unconditionally (as before) put
        # the literal string "IR:5000001" in every IR's case_id field, breaking
        # any downstream case_id lookup/filter for investigation reports.
        case_id = meta.get("case_master_id")
        if case_id is None:
            case_id = int(node_id) if str(node_id).isdigit() else node_id
        values = _embed(text, bedrock)
        vectors.append({
            "id": f"historical::{node_id}::{doc_type}",
            "values": values,
            "metadata": {
                "case_id": case_id,
                "doc_type": doc_type,
                "origin": "historical",
                "source": f"historical/docs/{meta.get('CrimeNo', node_id)}/{'fir.txt' if doc_type == 'FIR' else 'investigation_report.txt'}",
                "crime_no": meta.get("CrimeNo", ""),
                "district": meta.get("district", ""),
                "crime_type": meta.get("crime_type", ""),
            },
        })

    print(f"[pinecone-load] Embedded {len(vectors)} records ({skipped} skipped: empty text)")

    upserted = 0
    for i in range(0, len(vectors), BATCH_SIZE):
        batch = vectors[i : i + BATCH_SIZE]
        index.upsert(vectors=batch)
        upserted += len(batch)
        print(f"[pinecone-load] Upserted batch: {upserted}/{len(vectors)}")

    print(f"[pinecone-load] Completed successfully. {upserted} historical vectors upserted.")


if __name__ == "__main__":
    load()
