"""Single-command clean slate: wipe ALL data stores, then reload the historical
baseline (Postgres <- sqlite, Neo4j <- Postgres, Pinecone <- historical narratives).

Demo scenarios are NOT loaded here -- ingest them one at a time afterwards via
scratchpad/ingest_direct.py (each fuses its live docs onto this historical baseline).

Destructive. Requires --yes to actually run (dry-run prints the plan otherwise).

    python scripts/reset_and_reload_historical.py --yes
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (label, argv) run in order; each must exit 0 or the whole reload aborts.
# NOTE: wipe_all_data only clears raw/processed/archive in Stratus, NOT historical/docs/,
# so the doc upload below is what keeps Stratus in sync with a regenerated sample_data —
# without it the Pinecone `source` metadata (historical/docs/{CrimeNo}/...) points at stale
# or missing files. blob_store.run() re-uploads with overwrite semantics.
STEPS: list[tuple[str, list[str]]] = [
    ("wipe all stores", [sys.executable, str(ROOT / "scripts" / "wipe_all_data.py"), "--yes"]),
    ("historical -> Postgres (schema + seed + data)", [sys.executable, str(ROOT / "backend" / "migrations" / "migrate_sqlite_to_pg.py")]),
    ("historical docs -> Stratus (historical/docs/)", [sys.executable, "-c", "from data_ingestion.blob_store import run; run()"]),
    ("historical -> Neo4j", [sys.executable, str(ROOT / "backend" / "migrations" / "load_neo4j_from_pg.py")]),
    ("historical -> Pinecone", [sys.executable, str(ROOT / "backend" / "migrations" / "load_pinecone_from_historical.py")]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="Actually run. Without it, only prints the plan.")
    args = parser.parse_args()

    print(f"[reload] {'RUN' if args.yes else 'DRY-RUN'} — {len(STEPS)} steps, cwd={ROOT}")
    for i, (label, argv) in enumerate(STEPS, 1):
        print(f"  {i}. {label}\n     {' '.join(argv[1:])}")
    if not args.yes:
        print("\nDry-run only. Re-run with --yes to execute.")
        return 0

    for i, (label, argv) in enumerate(STEPS, 1):
        print(f"\n===== STEP {i}/{len(STEPS)}: {label} =====")
        t0 = time.time()
        rc = subprocess.run(argv, cwd=str(ROOT)).returncode
        dt = time.time() - t0
        if rc != 0:
            print(f"\n[reload] ABORT — step {i} ({label}) exited {rc} after {dt:.0f}s")
            return rc
        print(f"[reload] step {i} OK ({dt:.0f}s)")

    print("\n[reload] DONE — historical baseline reloaded. Ingest scenarios one at a time next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
