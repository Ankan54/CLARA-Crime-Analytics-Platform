"""
ingest.py — Staged ETL orchestrator for historical data ingestion.

Stages (in order):
    preflight -> blob_upload -> sql_load -> graph_load -> vector_load -> verify

Default: fresh rebuild (wipe all stores, reload from scratch).
Use --no-wipe to upsert/append instead.
Use --stages to run a subset: --stages sql_load vector_load

On any failure: writes failures.json and exits 1 (no store is left half-wiped silently
because preflight gates before any wipe begins).

Usage:
    python -m data_ingestion.ingest
    python -m data_ingestion.ingest --no-wipe
    python -m data_ingestion.ingest --stages sql_load vector_load verify
    python -m data_ingestion.ingest --stages graph_load --no-wipe
"""
from __future__ import annotations
import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Callable

from . import config as cfg


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------
def _stage_preflight(wipe: bool) -> None:
    from .preflight import run as _run
    _run()


def _stage_blob_upload(wipe: bool) -> None:
    from .blob_store import run as _run
    _run()


def _stage_sql_load(wipe: bool) -> None:
    from .sql_store import run as _run
    _run()


def _stage_pg_load(wipe: bool) -> None:
    from .pg_store import run as _run
    _run(wipe=wipe)


def _stage_graph_load(wipe: bool) -> None:
    from .graph_store import run as _run
    _run(wipe=wipe)


def _stage_vector_load(wipe: bool) -> None:
    from .vector_store import run as _run
    _run(wipe=wipe)


def _stage_verify(wipe: bool) -> None:
    from .verify import run as _run
    _run()


STAGES: dict[str, Callable[[bool], None]] = {
    "preflight":   _stage_preflight,
    "blob_upload": _stage_blob_upload,
    "sql_load":    _stage_sql_load,
    "pg_load":     _stage_pg_load,
    "graph_load":  _stage_graph_load,
    "vector_load": _stage_vector_load,
    "verify":      _stage_verify,
}
ALL_STAGES = list(STAGES.keys())


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run(stages: list[str] | None = None, wipe: bool = True) -> int:
    """
    Execute pipeline stages in order.
    Returns 0 on success, 1 on failure (also writes failures.json).
    """
    to_run = stages or ALL_STAGES
    unknown = [s for s in to_run if s not in STAGES]
    if unknown:
        print(f"[ingest] Unknown stage(s): {unknown}", flush=True)
        print(f"[ingest] Valid stages: {ALL_STAGES}", flush=True)
        return 1

    cfg.STATE_DIR.mkdir(parents=True, exist_ok=True)
    failures: dict[str, str] = {}

    print(f"\n[ingest] Pipeline starting — stages: {to_run}, wipe={wipe}", flush=True)

    for stage in to_run:
        print(f"\n{'='*60}", flush=True)
        print(f"[ingest] STAGE: {stage}", flush=True)
        print(f"{'='*60}", flush=True)
        try:
            STAGES[stage](wipe)
        except SystemExit as e:
            # preflight or verify called sys.exit — treat as stage failure
            msg = f"stage exited with code {e.code}"
            failures[stage] = msg
            print(f"\n[ingest] Stage '{stage}' FAILED: {msg}", flush=True)
            break
        except Exception as e:
            tb = traceback.format_exc()
            failures[stage] = f"{type(e).__name__}: {e}\n{tb}"
            print(f"\n[ingest] Stage '{stage}' FAILED: {e}", flush=True)
            print(tb, flush=True)
            break

    if failures:
        failures_path = cfg.FAILURES_FILE
        failures_path.write_text(json.dumps(failures, indent=2), encoding="utf-8")
        print(f"\n[ingest] FAILED. Failures written to {failures_path}", flush=True)
        return 1

    print(f"\n[ingest] Pipeline COMPLETE. All stages passed.", flush=True)
    # Remove stale failures file on success
    if cfg.FAILURES_FILE.exists():
        cfg.FAILURES_FILE.unlink()
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="KSP historical data ingestion ETL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Available stages: {', '.join(ALL_STAGES)}",
    )
    parser.add_argument(
        "--stages", nargs="+", metavar="STAGE",
        help="Run only these stages (space-separated). Default: all stages.",
    )
    parser.add_argument(
        "--no-wipe", action="store_true",
        help="Skip wipe — upsert/append instead of full rebuild.",
    )
    args = parser.parse_args()
    wipe = not args.no_wipe
    sys.exit(run(stages=args.stages, wipe=wipe))


if __name__ == "__main__":
    main()
