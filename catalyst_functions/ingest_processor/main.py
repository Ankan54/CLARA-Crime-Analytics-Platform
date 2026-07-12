from __future__ import annotations

import logging
import traceback
from typing import Any

import psycopg

from .pipeline.processor import IngestProcessor, RunParams, _build_database_url


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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
    raise ValueError(f"Unable to parse function params from event={event!r}")


def _mark_failed(run_id: str, stage: str, message: str) -> None:
    logger.error("marking run failed run_id=%s stage=%s: %s", run_id, stage, message[:200])
    try:
        with psycopg.connect(_build_database_url(), prepare_threshold=0) as conn:
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


def handler(event: Any = None, context: Any = None, **kwargs: Any) -> dict[str, Any]:
    params = _extract_params(event, kwargs)
    run_id = str(params.get("run_id", ""))
    phase = str(params.get("phase", "extract")).lower()
    logger.info("handler start run_id=%s phase=%s params=%s", run_id, phase, {k: v for k, v in params.items() if k != "run_id"})
    try:
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
        logger.exception("handler error run_id=%s phase=%s", run_id, phase)
        if run_id:
            _mark_failed(run_id, stage=f"{phase.upper()}_FAILED", message=err)
        return {"status": "error", "error": str(exc)}


def main(event: Any = None, context: Any = None, **kwargs: Any) -> dict[str, Any]:
    # Alias for Catalyst handlers that look for `main`.
    return handler(event=event, context=context, **kwargs)
