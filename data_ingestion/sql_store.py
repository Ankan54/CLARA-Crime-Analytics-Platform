"""
sql_store.py — Thin wrapper: delegate to data_generation.db_loader.build_db().
Already FK-checked and idempotent (unlinks + recreates ksp.sqlite each run).
"""
from __future__ import annotations

from . import config as cfg


def run() -> str:
    """Build ksp.sqlite. Returns path to the created DB file."""
    import sys
    sys.path.insert(0, str(cfg.ROOT))
    from data_generation.db_loader import build_db

    print("[sql_store] Building ksp.sqlite …", flush=True)
    db = build_db(
        sql_dir=str(cfg.SQL_DIR),
        db_path=str(cfg.DB_PATH),
        schema_path=str(cfg.SCHEMA_PATH),
    )
    print(f"[sql_store] Done -> {db}", flush=True)
    return db
