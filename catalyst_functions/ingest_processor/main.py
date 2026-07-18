from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any

import psycopg


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Bumped by hand before each zip/upload -- Job Scheduling has no equivalent of the
# backend's docker --build-arg BUILD_ID, and results aren't visible anywhere we can
# poll directly, so this is stamped into PipelineRun.files_progress._meta on every
# invocation (see _stamp_build_id) and shows up in GET /api/v1/pipeline-status/{run_id}.
FUNCTION_BUILD_ID = "20260716-person-dedup-fix"


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _build_database_url_safe() -> str:
    """Self-contained copy of pipeline.processor._build_database_url.

    Deliberately does not import from `.pipeline.processor` — that module pulls in
    docx/bs4/pypdf/langchain_core/pydantic/rapidfuzz at import time, and if any of
    those is missing or broken, `_mark_failed` below must still be able to report
    the failure. Keep this in sync with `_build_database_url` in pipeline/processor.py.
    """
    if _env("DATABASE_URL"):
        return _env("DATABASE_URL")
    host = _env("DB_HOST")
    port = _env("DB_PORT", "5432")
    user = _env("DB_USER")
    name = _env("DB_NAME", "ksp_crime")
    ssl = _env("DB_SSL", "require")
    password = _env("DB_PASSWORD").strip("\"'")
    # prepare_threshold is a psycopg.connect() kwarg, not a libpq/psycopg URI
    # parameter -- embedding it in the query string raises "invalid URI query
    # parameter" at connect time (confirmed live). _mark_failed passes
    # prepare_threshold=None explicitly instead.
    return f"postgresql://{user}:{password}@{host}:{port}/{name}?sslmode={ssl}"


def _extract_params(event: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    if kwargs.get("params"):
        return kwargs["params"]
    if isinstance(event, dict):
        if isinstance(event.get("params"), dict):
            return event["params"]
        if isinstance(event.get("data"), dict):
            data = event["data"]
            if isinstance(data.get("params"), dict):
                return data["params"]
            return data
        return event
    # Catalyst Job Functions call handler(job_request, context) -- job_request is a
    # runtime-injected `flavours.job.JobDetails` object, not a dict, and isn't part
    # of the pip-installable zcatalyst-sdk (so its interface isn't in our vendored
    # copy or public docs). Confirmed live via the public_attrs dump in the ValueError
    # below: it exposes get_all_job_params() -> dict, matching the "params" dict we
    # submit in catalyst_queue.py's job_meta. Other accessor names kept as fallbacks
    # in case a future SDK version renames this.
    for method in ("get_all_job_params", "get_params", "to_dict", "as_dict"):
        fn = getattr(event, method, None)
        if callable(fn):
            result = fn()
            if isinstance(result, dict):
                params = result.get("params")
                return params if isinstance(params, dict) else result
    value = getattr(event, "params", None)
    if callable(value):
        value = value()
    if isinstance(value, dict):
        return value
    raise ValueError(
        f"Unable to parse function params from event={event!r} type={type(event)!r} "
        f"public_attrs={[a for a in dir(event) if not a.startswith('_')]!r}"
    )


def _mark_failed(run_id: str, stage: str, message: str) -> None:
    logger.error("marking run failed run_id=%s stage=%s: %s", run_id, stage, message[:200])
    try:
        with psycopg.connect(_build_database_url_safe(), prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE PipelineRun
                    SET status = 'FAILED',
                        current_stage = %s,
                        error_stage = %s,
                        error_message = %s,
                        updated_at = NOW()
                    WHERE run_id = %s
                    """,
                    (stage, stage, message[:3000], run_id),
                )
            conn.commit()
        logger.debug("mark_failed: db updated run_id=%s stage=%s", run_id, stage)
    except Exception as exc:
        logger.error("mark_failed: could not update DB (run_id=%s): %s", run_id, exc)


def _stamp_build_id(run_id: str) -> None:
    """Best-effort: record which function build actually executed this run, so
    'is the deployed zip current?' is answerable via GET /pipeline-status/{run_id}
    (files_progress._meta.function_build_id) instead of guessing from QUEUED lag."""
    try:
        with psycopg.connect(_build_database_url_safe(), prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE PipelineRun
                    SET files_progress = jsonb_set(COALESCE(files_progress, '{}'::jsonb), '{_meta}',
                                                    %s::jsonb, true)
                    WHERE run_id = %s
                    """,
                    (json.dumps({"function_build_id": FUNCTION_BUILD_ID, "stamped_at": _utc_now()}), run_id),
                )
            conn.commit()
    except Exception as exc:
        logger.warning("stamp_build_id failed run_id=%s: %s", run_id, exc)


def handler(event: Any = None, context: Any = None, **kwargs: Any) -> dict[str, Any]:
    # Everything (including param extraction) lives inside this try -- a failure
    # before reaching pipeline.processor previously raised straight out of handler()
    # with zero DB trace (caught only by Catalyst's own platform-level log, not by
    # anything of ours), leaving the run stuck at QUEUED indefinitely with no
    # error_message anywhere. run_id/phase default to "" / "extract" so _mark_failed
    # still gets a best-effort stage label even if extraction itself is what failed.
    run_id = ""
    phase = "extract"
    try:
        params = _extract_params(event, kwargs)
        run_id = str(params.get("run_id", ""))
        phase = str(params.get("phase", "extract")).lower()
        logger.info("handler start run_id=%s phase=%s build=%s params=%s", run_id, phase, FUNCTION_BUILD_ID, {k: v for k, v in params.items() if k != "run_id"})
        if run_id:
            _stamp_build_id(run_id)

        # Deliberately lazy: importing pipeline.processor pulls in docx/bs4/pypdf/
        # langchain_core/pydantic/rapidfuzz. A missing/broken dependency there must
        # surface as a caught, reported failure (this try/except + _mark_failed)
        # rather than crashing module import before handler() is ever callable --
        # which previously left the run stuck at QUEUED forever, unreported.
        #
        # Two different loaders give main.py two different identities: the backend's
        # local-invoke path (INGEST_LOCAL_INVOKE=true) imports this file as the real
        # package submodule catalyst_functions.ingest_processor.main, where the
        # relative import resolves fine. The deployed Catalyst runtime loads main.py
        # standalone from /catalyst/ with pipeline/ as a flat sibling and no parent
        # package at all -- the relative form raises "attempted relative import with
        # no known parent package" there (confirmed live). Try relative first, fall
        # back to absolute; the failure happens before pipeline.processor's own code
        # runs, so retrying has no partial-import side effects to worry about.
        try:
            from .pipeline.processor import IngestProcessor, RunParams
        except ImportError:
            from pipeline.processor import IngestProcessor, RunParams

        run_params = RunParams(
            batch_id=str(params["batch_id"]),
            case_id=int(params["case_id"]),
            run_id=run_id,
            phase=phase,
        )
        processor = IngestProcessor(run_params)
        try:
            if phase == "load":
                result = processor.run_phase_b()
            else:
                result = processor.run_phase_a()
            logger.info("handler done run_id=%s phase=%s result=%s", run_id, phase, result)
            return {"status": "ok", "result": result}
        finally:
            processor.close()
    except Exception as exc:
        err = f"{exc}\n{traceback.format_exc()}"
        # The Catalyst console Logs tab does not render the traceback that
        # logger.exception()/exc_info=True normally attaches -- confirmed live: only
        # the literal formatted message string shows up, nothing after it. The
        # exception detail must be *in* the message itself to ever be visible there,
        # not just handed to _mark_failed (which is also a no-op when run_id is
        # empty, i.e. exactly the case -- extraction failure -- most likely to need
        # this fallback).
        logger.error("handler error run_id=%s phase=%s error=%s", run_id, phase, err)
        if run_id:
            _mark_failed(run_id, stage=f"{phase.upper()}_FAILED", message=err)
        return {"status": "error", "error": str(exc)}


def main(event: Any = None, context: Any = None, **kwargs: Any) -> dict[str, Any]:
    # Alias for Catalyst handlers that look for `main`.
    return handler(event=event, context=context, **kwargs)
