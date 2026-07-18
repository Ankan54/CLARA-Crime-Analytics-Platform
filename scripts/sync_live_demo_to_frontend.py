"""
sync_live_demo_to_frontend.py — Mirror sample_data/live_demo/ into
frontend/src/assets/live_demo/, which is the frontend's actual source of
truth for demo scenario documents (Vite bundles from there via
import.meta.glob, confirmed in frontend/src/data/scenarios.ts -- it does not
read from sample_data/ at all). Currently kept in sync by hand; this script
makes that automatic so a future data_generation regeneration of live_demo
docs doesn't silently leave the frontend serving stale content.

A no-op (identical copy) whenever live_demo document content hasn't changed --
safe to run any time.

Usage:
    python scripts/sync_live_demo_to_frontend.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sample_data" / "live_demo"
TARGET = ROOT / "frontend" / "src" / "assets" / "live_demo"


def sync() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"[sync-live-demo] source not found: {SOURCE}")

    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET)

    file_count = sum(1 for _ in TARGET.rglob("*") if _.is_file())
    print(f"[sync-live-demo] Mirrored {SOURCE} -> {TARGET} ({file_count} files)")


if __name__ == "__main__":
    sync()
