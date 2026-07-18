"""Manual verification script: embed a query phrase the same way the ingest
pipeline does (Bedrock amazon.titan-embed-text-v1) and run it against Pinecone,
first as pure semantic search across the whole index, then as a "hybrid" search
(vector similarity + metadata filter) scoped to one case -- this index is
dense-only (no sparse vectors configured), so metadata filtering is the
practical hybrid mechanism available here, not Pinecone's native sparse+dense
hybrid feature.

Usage:
    python scripts/pinecone_hybrid_search_test.py "your query phrase" [case_id]

Defaults to a paraphrase of the digital-arrest FIR narrative and case_id=1000063.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv
from pinecone import Pinecone

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

import os

DEFAULT_QUERY = (
    "A caller pretending to be a CBI officer scared a retired professor into "
    "sending money because his Aadhaar was supposedly linked to a money "
    "laundering case."
)


def embed(text: str) -> list[float]:
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    model = os.environ.get("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v1")
    bedrock = boto3.client("bedrock-runtime", region_name=region)
    resp = bedrock.invoke_model(modelId=model, body=json.dumps({"inputText": text}))
    return json.loads(resp["body"].read().decode("utf-8"))["embedding"]


def print_matches(label: str, matches: list) -> None:
    print(f"\n--- {label} ---")
    if not matches:
        print("  (no matches)")
        return
    for m in matches:
        meta = m.metadata or {}
        print(f"  id={m.id}  score={m.score:.4f}")
        print(f"    case_id={meta.get('case_id')} doc_type={meta.get('doc_type')} "
              f"run_id={meta.get('run_id')} source={meta.get('source')}")


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY
    case_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1000063

    print(f"Query phrase: {query!r}")
    print(f"Filtering case_id: {case_id}")

    vector = embed(query)
    print(f"Embedded to {len(vector)}-dim vector via amazon.titan-embed-text-v1")

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(os.environ.get("PINECONE_INDEX", "ksp-crime-intel"))

    # 1. Pure semantic search, no filter -- proves the FIR ranks highly on
    #    meaning alone, not because we told Pinecone which case to look in.
    unfiltered = index.query(vector=vector, top_k=5, include_metadata=True)
    print_matches("Pure semantic search (top 5, no filter)", unfiltered.matches)

    # 2. Hybrid: same vector, scoped with a metadata filter -- what the
    #    officer-facing assistant would actually do once a case is selected.
    filtered = index.query(
        vector=vector, top_k=5, include_metadata=True,
        filter={"case_id": {"$eq": case_id}},
    )
    print_matches(f"Hybrid search (vector + filter case_id={case_id})", filtered.matches)

    fir_hits = [m for m in filtered.matches if (m.metadata or {}).get("doc_type") == "FIR"]
    if fir_hits:
        top = fir_hits[0]
        print(f"\nPASS: FIR record found for case {case_id} -- id={top.id} score={top.score:.4f}")
        print(f"  full metadata: {top.metadata}")
    else:
        print(f"\nFAIL: no FIR record found in filtered results for case {case_id}")
        sys.exit(1)


if __name__ == "__main__":
    main()
