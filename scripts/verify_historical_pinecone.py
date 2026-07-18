"""verify_historical_pinecone.py -- durable check that historical FIR/IR text
loaded into Pinecone by load_pinecone_from_historical.py is correctly indexed
and findable.

Three checks per sample case (spanning scenario-critical and plain background
FIRs), matching the two-step methodology scripts/pinecone_hybrid_search_test.py
already uses (pure semantic first, then case-scoped hybrid):
  1. HARD: embedding the case's own full fir.txt text and querying unfiltered
     returns that exact record as the #1 match (near-1.0 self-similarity) --
     proves the loader indexed the right text under the right id.
  2. HARD: embedding a hand-written paraphrase and filtering by case_id finds
     the record at all -- proves case_id metadata is correct, matching
     pinecone_hybrid_search_test.py's own pass bar ("found in filtered
     results", not literally rank-1 unfiltered).
  3. INFORMATIONAL ONLY: the same paraphrase, unfiltered, reports where the
     case ranks globally. Historical narratives reuse a lot of scam-template
     language across similar-MO cases (confirmed live: a paraphrase of case
     1000001's TRAI/CBI digital-arrest FIR ranked *other* digital-arrest
     IRs higher by raw score) -- a paraphrase surfacing genuinely similar
     cases ahead of its own source is the "find similar cases" feature
     working, not a loader bug, so this doesn't fail the script. Narrative
     distinctiveness is a content-quality question, deferred to Phase 2.

Exit code 0 and "ALL CHECKS PASSED" iff every HARD check passes.
Read-only against Pinecone (queries only, no upserts/deletes).

Usage:
    python scripts/verify_historical_pinecone.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv
from pinecone import Pinecone

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# Each entry: (case_id, crime_no -- to locate fir.txt on disk, hand-written
# paraphrase of that case's actual narrative -- confirmed against the real
# file before writing, not copied verbatim, label).
_CASES = [
    (
        1000001,
        "129031010202600001",
        "A retired IAS officer in Mysuru was tricked by callers posing as TRAI "
        "and CBI officials into believing his Aadhaar was linked to a money "
        "laundering case, and was kept on a video call (digital arrest) until "
        "he transferred a large sum by NEFT.",
        "scenario1 digital-arrest (Suresh Venkataraman, Mysuru)",
    ),
    (
        1000020,
        "129011005202600002",
        "An unemployed graduate in Bengaluru was recruited into a Telegram "
        "task-based job scam, made a small test payment, then paid a larger "
        "deposit via UPI before the operators went silent and withdrawals were "
        "blocked.",
        "scenario4 burst (Nagaraj Gowda, Whitefield task scam)",
    ),
    (
        1000050,
        "129011001202600006",
        "A young fresher named Nalini Patil filed a cyber fraud complaint at "
        "CEN Police Station East Division in Bengaluru in March 2026.",
        "plain background FIR (Nalini Patil, CEN East Division)",
    ),
]


def embed(text: str) -> list[float]:
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    model = os.environ.get("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v1")
    bedrock = boto3.client("bedrock-runtime", region_name=region)
    resp = bedrock.invoke_model(modelId=model, body=json.dumps({"inputText": text}))
    return json.loads(resp["body"].read().decode("utf-8"))["embedding"]


def main() -> int:
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(os.environ.get("PINECONE_INDEX", "ksp-crime-intel"))

    failures: list[str] = []
    for case_id, crime_no, paraphrase, label in _CASES:
        print(f"\n--- {label} (case_id={case_id}) ---")
        expected_id = f"historical::{case_id}::FIR"

        # 1. HARD: full-text self-match
        fir_path = ROOT / "sample_data" / "historical" / "docs" / crime_no / "fir.txt"
        full_text = fir_path.read_text(encoding="utf-8")
        self_result = index.query(vector=embed(full_text), top_k=1, include_metadata=True)
        if self_result.matches and self_result.matches[0].id == expected_id and self_result.matches[0].score > 0.99:
            print(f"  PASS  full-text self-match: id={self_result.matches[0].id} score={self_result.matches[0].score:.4f}")
        else:
            got = self_result.matches[0].id if self_result.matches else "(no matches)"
            got_score = self_result.matches[0].score if self_result.matches else 0.0
            failures.append(f"{label}: full-text self-match got id={got} score={got_score:.4f}, expected id={expected_id} score>0.99")
            print(f"  FAIL  full-text self-match: id={got} score={got_score:.4f}")

        # 2. HARD: paraphrase + case_id filter finds the record
        para_vector = embed(paraphrase)
        filtered = index.query(vector=para_vector, top_k=3, include_metadata=True, filter={"case_id": {"$eq": case_id}})
        fir_hits = [m for m in filtered.matches if (m.metadata or {}).get("doc_type") == "FIR"]
        if fir_hits:
            print(f"  PASS  paraphrase + case_id filter finds it: id={fir_hits[0].id} score={fir_hits[0].score:.4f}")
        else:
            failures.append(f"{label}: paraphrase + case_id={case_id} filter found no FIR record")
            print(f"  FAIL  paraphrase + case_id filter: no FIR record found")

        # 3. INFORMATIONAL: unfiltered paraphrase rank
        unfiltered = index.query(vector=para_vector, top_k=10, include_metadata=True)
        rank = next((i + 1 for i, m in enumerate(unfiltered.matches) if m.id == expected_id), None)
        if rank:
            print(f"  INFO  unfiltered paraphrase rank: #{rank} of top 10 (score={unfiltered.matches[rank - 1].score:.4f})")
        else:
            print(f"  INFO  unfiltered paraphrase rank: outside top 10 -- other similar-MO cases ranked higher")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s) failed.")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
