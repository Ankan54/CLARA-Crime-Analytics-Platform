from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings


# India DC overrides must be present before zcatalyst_sdk import.
os.environ.setdefault("X_ZOHO_CATALYST_ACCOUNTS_URL", settings.zoho_auth_domain)
os.environ.setdefault("X_ZOHO_CATALYST_CONSOLE_URL", settings.zoho_project_domain)
os.environ.setdefault("X_ZOHO_STRATUS_RESOURCE_SUFFIX", ".zohostratus.in")
logger = logging.getLogger(__name__)


_token_cache: dict[str, str | float | None] = {"token": None, "expires_at": 0.0}


@dataclass
class QueueSubmissionResult:
    job_id: str | None
    queue_status: str
    queue_response: dict[str, Any] | None


def _patch_zcatalyst_url_join() -> None:
    from zcatalyst_sdk._http_client import HttpClient

    if getattr(HttpClient.request, "_ksp_patched", False):
        logger.debug("zcatalyst url patch already applied")
        return
    original = HttpClient.request

    def _request(self, method, url=None, path=None, *args, **kwargs):
        if url is None and path and str(path).startswith("/oauth"):
            path = path.lstrip("/")
        return original(self, method, url, path, *args, **kwargs)

    _request._ksp_patched = True  # type: ignore[attr-defined]
    HttpClient.request = _request  # type: ignore[method-assign]
    logger.debug("zcatalyst url patch applied")


def _get_access_token() -> str:
    now = time.time()
    token = _token_cache["token"]
    expires_at = float(_token_cache["expires_at"] or 0.0)
    if token and now < expires_at - 60:
        logger.debug("access token cache hit expires_at=%s", expires_at)
        return str(token)

    logger.debug("refreshing access token auth_domain=%s client_id=%s", settings.zoho_auth_domain, settings.zoho_client_id)
    try:
        response = requests.post(
            f"{settings.zoho_auth_domain}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.zoho_client_id,
                "client_secret": settings.zoho_client_secret,
                "refresh_token": settings.zoho_refresh_token,
            },
            timeout=20,
        )
    except Exception:
        logger.exception("access token refresh request failed")
        raise
    response.raise_for_status()
    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        logger.error("access token refresh failed payload=%s", payload)
        raise RuntimeError(f"Token refresh failed: {payload}")
    _token_cache["token"] = access_token
    _token_cache["expires_at"] = now + float(payload.get("expires_in", 3600))
    logger.debug("access token refresh success expires_in=%s", payload.get("expires_in", 3600))
    return str(access_token)


def _init_app():
    import zcatalyst_sdk
    from zcatalyst_sdk import credentials, types

    _patch_zcatalyst_url_join()
    try:
        # Works when this process itself runs inside Catalyst (e.g. deployed to
        # AppSail) — the project identity is injected implicitly, no OAuth needed.
        app = zcatalyst_sdk.get_app()
        logger.debug("catalyst app reuse via get_app")
        return app
    except Exception:
        logger.debug("catalyst get_app unavailable; falling back to initialize_app", exc_info=True)

    cred = credentials.RefreshTokenCredential(
        {
            "refresh_token": settings.zoho_refresh_token,
            "client_id": settings.zoho_client_id,
            "client_secret": settings.zoho_client_secret,
        }
    )
    options = types.ICatalystOptions(
        project_id=settings.zoho_project_id,
        project_key=settings.zoho_project_key,
        environment=settings.zoho_environment,
        project_domain=settings.zoho_project_domain,
    )
    try:
        app = zcatalyst_sdk.initialize_app(credential=cred, options=options)
        logger.debug("catalyst app initialized project_id=%s env=%s", settings.zoho_project_id, settings.zoho_environment)
        return app
    except Exception:
        logger.exception("catalyst initialize_app failed project_id=%s env=%s", settings.zoho_project_id, settings.zoho_environment)
        raise


def _safe_name(filename: str) -> str:
    return filename.replace("\\", "_").replace("/", "_")


def build_raw_key(batch_id: str, file_type: str, filename: str) -> str:
    return f"raw/{batch_id}/{file_type.strip().lower()}_{_safe_name(filename)}"


def build_processed_prefix(case_id: int, run_id: str) -> str:
    return f"processed/{case_id}/{run_id}/"


def build_archive_key(case_id: int, run_id: str, file_type: str, filename: str) -> str:
    return f"archive/{case_id}/{run_id}/{file_type.strip().lower()}_{_safe_name(filename)}"


def upload_file_to_stratus(key: str, data: bytes) -> str:
    logger.info("stratus upload start bucket=%s key=%s size=%d", settings.zoho_stratus_bucket, key, len(data))
    app = _init_app()
    bucket = app.stratus().bucket(settings.zoho_stratus_bucket)
    try:
        bucket.put_object(key, data, options={"overwrite": "true"})
    except Exception:
        logger.exception("stratus upload failed bucket=%s key=%s", settings.zoho_stratus_bucket, key)
        raise
    logger.info("stratus upload done bucket=%s key=%s", settings.zoho_stratus_bucket, key)
    return f"stratus://{settings.zoho_stratus_bucket}/{key}"


def get_object_text(key: str) -> str:
    logger.debug("stratus get_object_text key=%s", key)
    app = _init_app()
    bucket = app.stratus().bucket(settings.zoho_stratus_bucket)
    try:
        obj = bucket.get_object(key)
    except Exception:
        logger.exception("stratus get_object failed key=%s", key)
        raise
    data = obj if isinstance(obj, bytes) else obj.read()
    logger.debug("stratus get_object_text done key=%s size=%d", key, len(data))
    return data.decode("utf-8")


def get_checkpoint_manifest(case_id: int, run_id: str) -> dict[str, Any]:
    """Read the Phase A checkpoint written by the ingest_processor function."""
    key = build_processed_prefix(case_id, run_id) + "manifest.json"
    logger.debug("checkpoint manifest read case_id=%s run_id=%s key=%s", case_id, run_id, key)
    try:
        manifest = json.loads(get_object_text(key))
    except Exception:
        logger.exception("checkpoint manifest read failed case_id=%s run_id=%s key=%s", case_id, run_id, key)
        raise
    logger.debug("checkpoint manifest read done case_id=%s run_id=%s files=%d", case_id, run_id, len(manifest.get("files", [])))
    return manifest


def list_raw_objects(batch_id: str) -> list[dict[str, Any]]:
    """List every object under raw/{batch_id}/ (file_type discovered from the key prefix)."""
    logger.debug("list_raw_objects start batch_id=%s", batch_id)
    app = _init_app()
    bucket = app.stratus().bucket(settings.zoho_stratus_bucket)
    prefix = f"raw/{batch_id}/"
    objects: list[dict[str, Any]] = []
    next_token = None
    while True:
        try:
            page = bucket.list_paged_objects(prefix=prefix, next_token=next_token)
        except Exception:
            logger.exception("list_raw_objects failed batch_id=%s prefix=%s", batch_id, prefix)
            raise
        for obj in page["contents"]:
            key = obj.to_dict().get("key") if hasattr(obj, "to_dict") else obj.get("key")
            if key:
                objects.append({"key": key})
        if not page.get("truncated"):
            break
        next_token = page.get("next_continuation_token")
    logger.debug("list_raw_objects done batch_id=%s count=%d", batch_id, len(objects))
    return objects


def move_to_archive(case_id: int, run_id: str, batch_id: str) -> list[str]:
    """Move every raw/{batch_id}/* object to archive/{case_id}/{run_id}/*, preserving the filename part."""
    logger.info("move_to_archive start case_id=%s run_id=%s batch_id=%s", case_id, run_id, batch_id)
    app = _init_app()
    bucket = app.stratus().bucket(settings.zoho_stratus_bucket)
    moved: list[str] = []
    for entry in list_raw_objects(batch_id):
        raw_key = entry["key"]
        archive_key = f"archive/{case_id}/{run_id}/" + raw_key.rsplit("/", 1)[-1]
        try:
            bucket.rename_object(raw_key, archive_key)
        except Exception:
            logger.warning("move_to_archive rename failed raw=%s archive=%s; trying copy+delete", raw_key, archive_key, exc_info=True)
            bucket.copy_object(raw_key, archive_key)
            bucket.delete_object(raw_key)
        moved.append(archive_key)
    logger.info("move_to_archive done case_id=%s run_id=%s moved=%d", case_id, run_id, len(moved))
    return moved


def _submit_job_via_sdk(params: dict[str, str], run_id: str) -> dict[str, Any]:
    logger.info("submit_job_via_sdk start run_id=%s params_keys=%s", run_id, sorted(params.keys()))
    app = _init_app()
    job_meta: dict[str, Any] = {
        "job_name": f"ingest-{run_id}",
        "jobpool_name": settings.catalyst_jobpool_name,
        "target_type": "Function",
        "target_name": settings.catalyst_function_name,
        "params": {k: str(v) for k, v in params.items()},
        "job_config": {"number_of_retries": 2, "retry_interval": 900},
    }
    if settings.catalyst_jobpool_id:
        job_meta["jobpool_id"] = settings.catalyst_jobpool_id
    if settings.catalyst_function_id:
        job_meta["target_id"] = settings.catalyst_function_id
    try:
        result = app.job_scheduling().job.submit_job(job_meta)
    except Exception:
        logger.exception("submit_job_via_sdk failed run_id=%s", run_id)
        raise
    logger.info("submit_job_via_sdk done run_id=%s", run_id)
    return result


def _submit_job_via_rest(params: dict[str, str], run_id: str) -> dict[str, Any]:
    endpoint = settings.catalyst_job_submit_rest_url
    if not endpoint:
        endpoint = (
            f"{settings.zoho_project_domain}/baas/v1/project/"
            f"{settings.zoho_project_id}/job_scheduling/job"
        )

    payload: dict[str, Any] = {
        "job_name": f"ingest-{run_id}",
        "jobpool_name": settings.catalyst_jobpool_name,
        "target_type": "Function",
        "target_name": settings.catalyst_function_name,
        "params": {k: str(v) for k, v in params.items()},
        "source_type": "API",
    }
    if settings.catalyst_jobpool_id:
        payload["jobpool_id"] = settings.catalyst_jobpool_id
    if settings.catalyst_function_id:
        payload["target_id"] = settings.catalyst_function_id

    logger.info("submit_job_via_rest start run_id=%s endpoint=%s", run_id, endpoint)
    try:
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Zoho-oauthtoken {_get_access_token()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
    except Exception:
        logger.exception("submit_job_via_rest request failed run_id=%s endpoint=%s", run_id, endpoint)
        raise
    response.raise_for_status()
    body = response.json()
    logger.info("submit_job_via_rest done run_id=%s endpoint=%s", run_id, endpoint)
    return body.get("data", body)


def submit_ingestion_job(session: Session, run_id: str, params: dict[str, str]) -> QueueSubmissionResult:
    logger.info("submit_ingestion_job start run_id=%s phase=%s", run_id, params.get("phase"))
    try:
        result = _submit_job_via_sdk(params=params, run_id=run_id)
        job_id = result.get("job_id") or result.get("id")
        queue_status = "SUBMITTED"
        queue_payload = result
    except Exception as sdk_error:
        logger.warning("submit_ingestion_job sdk path failed run_id=%s; trying REST fallback", run_id, exc_info=True)
        try:
            result = _submit_job_via_rest(params=params, run_id=run_id)
            job_id = result.get("job_id") or result.get("id")
            queue_status = "SUBMITTED_REST_FALLBACK"
            queue_payload = {"sdk_error": str(sdk_error), "rest_result": result}
        except Exception as rest_error:
            logger.exception("submit_ingestion_job REST fallback failed run_id=%s", run_id)
            queue_status = "FAILED"
            queue_payload = {"sdk_error": str(sdk_error), "rest_error": str(rest_error)}
            job_id = None

    session.execute(
        text(
            """
            UPDATE PipelineRun
            SET status = :status,
                updated_at = NOW(),
                error_message = :error_message
            WHERE run_id = :run_id
            """
        ),
        {
            "status": "QUEUED" if queue_status != "FAILED" else "FAILED",
            "error_message": None if queue_status != "FAILED" else str(queue_payload),
            "run_id": run_id,
        },
    )
    logger.info("submit_ingestion_job done run_id=%s queue_status=%s job_id=%s", run_id, queue_status, job_id)
    return QueueSubmissionResult(job_id=job_id, queue_status=queue_status, queue_response=queue_payload)

