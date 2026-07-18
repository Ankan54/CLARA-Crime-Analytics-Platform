"""Sweeps PipelineRun rows that were submitted to the ingestion queue but never
ran: a cold-start failure, a dropped job, or a Catalyst platform hiccup means no
code ever executes for that run, so nothing else can move it off QUEUED/RUNNING --
the exception-handling in main.py/catalyst_queue.py only fires once a job actually
starts running. This is the last-resort backstop for that gap: any read of run
status also reaps rows that have made no progress for `run_stale_timeout_seconds`.

REVIEW_PENDING is a legitimate idle state (waiting on an officer to click Proceed)
and is never touched here.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings

logger = logging.getLogger(__name__)

_STALE_REAP_SQL = """
    UPDATE PipelineRun
    SET status = 'FAILED',
        current_stage = 'STALE_TIMEOUT',
        error_stage = 'STALE_TIMEOUT',
        error_message = 'No progress for over ' || :timeout_seconds || ' seconds -- '
            || 'the ingestion job likely never started (queue drop or cold-start '
            || 'failure). Use Retry to resubmit.',
        updated_at = NOW()
    WHERE status IN ('QUEUED', 'RUNNING')
      AND updated_at < NOW() - (:timeout_seconds * INTERVAL '1 second')
      AND (run_id = :run_id OR :run_id IS NULL)
    RETURNING run_id
"""
# Param order matters here: `run_id = :run_id` must appear before `:run_id IS NULL`
# so Postgres can infer :run_id's type from the column comparison. The reverse
# order (IS NULL checked first) raised psycopg.errors.AmbiguousParameter --
# confirmed against the live DB, not just reasoned about.


def reap_stale_runs(db: Session, run_id: str | None = None) -> list[str]:
    """Mark stuck runs FAILED. Pass run_id to scope to one run (cheap, used on
    every status read); omit it to sweep everything (used on list endpoints).
    Commits on its own -- safe to call at the top of a request before any other
    work in the same session, including inside a WebSocket poll loop.

    Best-effort: this now runs inside what used to be pure status-read paths
    (get_pipeline_status, the WS poll loop, list_runs, get_batch), polled every
    few seconds by every open run. If the UPDATE itself ever fails, that must not
    take the read down with it -- roll back (a failed statement leaves the
    session's transaction unusable for anything else until then) and let the
    caller's own SELECT proceed untouched.
    """
    try:
        result = db.execute(
            text(_STALE_REAP_SQL),
            {"timeout_seconds": settings.run_stale_timeout_seconds, "run_id": run_id},
        )
        reaped = [row[0] for row in result.fetchall()]
        db.commit()
    except Exception:
        logger.exception("reap_stale_runs: sweep failed (run_id=%s) -- skipping this cycle", run_id)
        db.rollback()
        return []
    if reaped:
        logger.warning(
            "reap_stale_runs: marked %d run(s) FAILED after %ds with no progress: %s",
            len(reaped), settings.run_stale_timeout_seconds, reaped,
        )
    return reaped
