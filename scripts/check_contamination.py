"""Check if evidence or live demo content leaked into vector/graph DBs."""
import json
from pathlib import Path
from collections import Counter

# --- 1. Check narratives.jsonl (source for Pinecone) ---
narr = Path("sample_data/historical/vector/narratives.jsonl")
records = [json.loads(l) for l in narr.read_text(encoding="utf-8").splitlines() if l.strip()]
print(f"Total records in narratives.jsonl: {len(records)}")

types = Counter(r.get("doc_type", "unknown") for r in records)
print(f"Doc types: {dict(types)}")

# Node IDs — any live/demo/scn/scenario references?
live_ids = [r["node_id"] for r in records if any(kw in str(r.get("node_id", "")).lower() for kw in ["live", "demo", "scn", "scenario"])]
print(f"Live/demo/scenario node_ids: {live_ids}")

# FIR and IR ID ranges
fir_ids = sorted(int(r["node_id"]) for r in records if r.get("doc_type") == "fir")
ir_ids = sorted(r["node_id"] for r in records if r.get("doc_type") == "investigation_report")
print(f"FIR IDs: {fir_ids[0]}-{fir_ids[-1]} ({len(fir_ids)} total)")
print(f"IR IDs: {ir_ids[:5]} ... ({len(ir_ids)} total)")

# Check for evidence file content embedded in the text
evidence_terms = [
    "call_log.csv", "transaction_ledger", "bsa_63_certificate",
    "device_forensics", "device_pool", "messaging_screenshot",
    "README_EVIDENCE_GAP",
]
print("\nEvidence content check in narrative texts:")
for term in evidence_terms:
    matches = [r["node_id"] for r in records if term in r.get("text", "")]
    if matches:
        print(f"  LEAK  '{term}' found in records: {matches}")
    else:
        print(f"  OK    '{term}' not in any record")

# --- 2. Check graph CSVs for evidence/demo nodes ---
print("\n--- Graph CSVs check ---")
GRAPH_DIR = Path("sample_data/historical/graph")
import csv
for f in sorted(GRAPH_DIR.glob("*.csv")):
    with open(f, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    # Check for any scenario/evidence/live/demo references in node_ids or values
    suspect = []
    for row in rows:
        vals = " ".join(str(v) for v in row.values()).lower()
        if any(kw in vals for kw in ["evidence", "live_scn", "live_demo", "scenario_"]):
            suspect.append(row)
    if suspect:
        print(f"  LEAK  {f.name}: {len(suspect)} suspect rows")
        for r in suspect[:2]:
            print(f"        {r}")
    else:
        print(f"  OK    {f.name}")
