from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .db import db_session
from .routers import (
    assistant,
    cases,
    demo_scenarios,
    internal,
    process,
    review,
    schema_admin,
    status,
    upload,
)


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_check() -> None:
    # Log a sanitised config summary so we can see which vars landed at runtime.
    logger.info(
        "Startup config: db_host=%s db_port=%s db_name=%s db_user=%s "
        "zoho_project=%s stratus_bucket=%s listen_port=%s",
        os.getenv("DB_HOST", "<not set>"),
        os.getenv("DB_PORT", "<not set>"),
        os.getenv("DB_NAME", "<not set>"),
        os.getenv("DB_USER", "<not set>"),
        settings.zoho_project_id or "<not set>",
        settings.zoho_stratus_bucket or "<not set>",
        settings.listen_port,
    )
    try:
        with db_session() as db:
            db.execute(text("SELECT 1"))
        logger.info("Database startup check passed.")
    except Exception:
        logger.exception(
            "FATAL: Database startup check failed — DB_HOST=%s  DB_NAME=%s  DB_USER=%s",
            os.getenv("DB_HOST", "<not set>"),
            os.getenv("DB_NAME", "<not set>"),
            os.getenv("DB_USER", "<not set>"),
        )
        raise


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "build_id": os.getenv("BUILD_ID", "unknown")}


app.include_router(cases.router, prefix=settings.api_prefix)
app.include_router(upload.router, prefix=settings.api_prefix)
app.include_router(process.router, prefix=settings.api_prefix)
app.include_router(demo_scenarios.router, prefix=settings.api_prefix)
app.include_router(assistant.router, prefix=settings.api_prefix)
app.include_router(schema_admin.router)
app.include_router(review.router)
app.include_router(status.router)
app.include_router(internal.router)
# No prefix: the frontend strips /api/v1 before dialling /ws/assistant/{run_id}
# (buildAssistantWsUrl in assistantClient.ts), matching the /ws/pipeline convention.
app.include_router(assistant.ws_router)

