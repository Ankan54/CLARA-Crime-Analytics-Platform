"""Chat persistence: sessions, turns, artifacts, per-officer memory.

Everything here is synchronous (db.py is sync SQLAlchemy), so callers on the event loop
must wrap these in asyncio.to_thread -- see routers/assistant.py.

Artifacts are stored twice on purpose: the row in Postgres carries metadata plus a small
inline body so history replay can redraw chips and tables without a Stratus round-trip,
while Stratus holds the durable copy and is the only home for PDF bytes.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text

from ..db import db_session
from .events import AssistantArtifact

logger = logging.getLogger(__name__)

STRATUS_PREFIX = "assistant"
# Anything bigger than this is Stratus-only; a graph with hundreds of nodes has no
# business sitting in a JSONB column we read on every history load.
INLINE_BODY_MAX_BYTES = 256 * 1024


# --- sessions ----------------------------------------------------------------


def ensure_session(session_id: str | None, user_id: str, title: str, case_id: int | None,
                   language: str) -> str:
    """Return an existing session id, or create one. Idempotent."""
    sid = session_id or f"sess-{uuid.uuid4().hex[:12]}"
    with db_session() as db:
        db.execute(text("""
            INSERT INTO AssistantSession(session_id, user_id, title, case_id, language)
            VALUES (:sid, :uid, :title, :case_id, :lang)
            ON CONFLICT (session_id) DO UPDATE
              SET updated_at = NOW(),
                  -- Later turns must not blank out context the session already had.
                  case_id = COALESCE(EXCLUDED.case_id, AssistantSession.case_id),
                  language = EXCLUDED.language
        """), {"sid": sid, "uid": user_id, "title": (title or "")[:120],
               "case_id": case_id, "lang": language})
    return sid


def list_sessions(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with db_session() as db:
        rows = db.execute(text("""
            SELECT session_id, title, case_id, language, updated_at
            FROM AssistantSession WHERE user_id = :uid
            ORDER BY updated_at DESC LIMIT :lim
        """), {"uid": user_id, "lim": limit}).mappings().all()
    return [dict(r) for r in rows]


def load_history(session_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Recent turns, oldest first -- the shape build_history() expects."""
    with db_session() as db:
        rows = db.execute(text("""
            SELECT role, content, run_id, payload, created_at FROM (
                SELECT role, content, run_id, payload, created_at, message_id
                FROM AssistantMessage WHERE session_id = :sid
                ORDER BY message_id DESC LIMIT :lim
            ) recent ORDER BY message_id ASC
        """), {"sid": session_id, "lim": limit}).mappings().all()
    return [dict(r) for r in rows]


def save_message(session_id: str, role: str, content: str, run_id: str | None = None,
                 payload: dict[str, Any] | None = None) -> None:
    with db_session() as db:
        db.execute(text("""
            INSERT INTO AssistantMessage(session_id, run_id, role, content, payload)
            VALUES (:sid, :rid, :role, :content, CAST(:payload AS jsonb))
        """), {"sid": session_id, "rid": run_id, "role": role, "content": content or "",
               "payload": json.dumps(payload or {})})
        db.execute(text("UPDATE AssistantSession SET updated_at = NOW() WHERE session_id = :sid"),
                   {"sid": session_id})


# --- artifacts ---------------------------------------------------------------


def save_artifact(artifact: AssistantArtifact, session_id: str, run_id: str,
                  stratus_key: str | None = None) -> None:
    # mode="json" so datetime/Decimal in Any-typed table rows serialise (see to_wire).
    body = artifact.model_dump(by_alias=True, exclude_none=True, mode="json")
    encoded = json.dumps(body)
    inline = encoded if len(encoded.encode("utf-8")) <= INLINE_BODY_MAX_BYTES else None
    with db_session() as db:
        db.execute(text("""
            INSERT INTO AssistantArtifact(artifact_id, session_id, run_id, kind, title, stratus_key, body)
            VALUES (:aid, :sid, :rid, :kind, :title, :key, CAST(:body AS jsonb))
            ON CONFLICT (artifact_id) DO NOTHING
        """), {"aid": artifact.id, "sid": session_id, "rid": run_id, "kind": artifact.kind,
               "title": artifact.title, "key": stratus_key, "body": inline})


def save_pdf_bytes(artifact_id: str, pdf: bytes) -> None:
    """Keep the rendered PDF alongside its row so a download never depends on Stratus."""
    save_blob(artifact_id, pdf)


def save_blob(artifact_id: str, blob: bytes) -> None:
    """Keep generated artifact bytes alongside the row."""
    with db_session() as db:
        db.execute(text("UPDATE AssistantArtifact SET blob = :b WHERE artifact_id = :aid"),
                   {"b": blob, "aid": artifact_id})


def load_artifact(artifact_id: str) -> dict[str, Any] | None:
    with db_session() as db:
        row = db.execute(text("""
            SELECT artifact_id, kind, title, stratus_key, body, blob
            FROM AssistantArtifact WHERE artifact_id = :aid
        """), {"aid": artifact_id}).mappings().first()
    return dict(row) if row else None


def load_session_artifacts(session_id: str) -> list[dict[str, Any]]:
    """Every inline artifact body produced across the whole session, oldest first.

    The report skill uses this so 'put all the findings in the chat into a PDF' attaches
    the tables/graphs/charts from EVERY turn -- not just the current run's bus history,
    which only holds the current turn and is swept once the run ends.
    """
    with db_session() as db:
        rows = db.execute(text("""
            SELECT body FROM AssistantArtifact
            WHERE session_id = :sid AND body IS NOT NULL
            ORDER BY created_at ASC, artifact_id ASC
        """), {"sid": session_id}).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        body = r["body"]
        if isinstance(body, str):  # jsonb usually decodes to dict, but be defensive
            try:
                body = json.loads(body)
            except Exception:
                continue
        if isinstance(body, dict):
            out.append(body)
    return out


def persist_run_artifacts(session_id: str, run_id: str, events: list[dict[str, Any]]) -> None:
    """Save every artifact a run emitted, from its event log.

    Reading them off the log rather than hooking the emitter keeps persistence out of the
    streaming path entirely -- a slow database write can never stall a token on its way to
    the browser.
    """
    from .events import DocumentArtifact, GraphArtifact, TableArtifact

    by_kind = {"graph": GraphArtifact, "table": TableArtifact, "document": DocumentArtifact}
    for event in events:
        if event.get("type") != "artifact":
            continue
        payload = event.get("artifact") or {}
        model = by_kind.get(payload.get("kind"))
        if not model:
            continue
        try:
            save_artifact(model.model_validate(payload), session_id, run_id)
        except Exception:
            logger.exception("assistant: could not persist artifact %s", payload.get("id"))


# --- memory ------------------------------------------------------------------


def load_memories(user_id: str, limit: int = 20) -> list[str]:
    with db_session() as db:
        rows = db.execute(text("""
            SELECT content FROM AssistantUserMemory
            WHERE user_id = :uid AND active ORDER BY updated_at DESC LIMIT :lim
        """), {"uid": user_id, "lim": limit}).mappings().all()
    return [r["content"] for r in rows]


def save_memory(user_id: str, content: str, kind: str = "preference",
                source_run_id: str | None = None) -> None:
    """Record something durable about this officer.

    Re-stating an existing memory refreshes it rather than adding a duplicate -- an
    officer who says "remember I work Bengaluru cyber" twice should not end up with the
    same line injected into the prompt twice.
    """
    with db_session() as db:
        updated = db.execute(text("""
            UPDATE AssistantUserMemory SET updated_at = NOW(), active = TRUE
            WHERE user_id = :uid AND lower(content) = lower(:content)
        """), {"uid": user_id, "content": content}).rowcount
        if not updated:
            db.execute(text("""
                INSERT INTO AssistantUserMemory(user_id, kind, content, source_run_id)
                VALUES (:uid, :kind, :content, :rid)
            """), {"uid": user_id, "kind": kind, "content": content, "rid": source_run_id})
    logger.info("assistant: memory saved user=%s kind=%s", user_id, kind)


def build_memory_tool(user_id: str, run_id: str):
    """A supervisor-only tool for explicit 'remember that ...' requests.

    Bound to this user's id at construction: the LLM cannot choose whose memory it
    writes to, so one officer's request can never touch another's profile.
    """
    from langchain_core.tools import StructuredTool

    def _save_memory(content: str, kind: str = "preference") -> str:
        cleaned = (content or "").strip()
        if not cleaned:
            return "Nothing to remember."
        save_memory(user_id, cleaned, kind=kind, source_run_id=run_id)
        return f"Saved to your profile: {cleaned}"

    return StructuredTool.from_function(
        func=_save_memory,
        coroutine=_as_async(_save_memory),
        name="save_memory",
        description=(
            "Remember a durable fact or preference about THIS officer for future sessions "
            "(their jurisdiction, speciality, or how they want answers). "
            "Use only when they explicitly ask you to remember something, or state a lasting "
            "preference. Do not use it for case facts -- those live in the databases."
        ),
    )


def _as_async(fn):
    import asyncio

    async def run(**kwargs):
        return await asyncio.to_thread(fn, **kwargs)

    run.__name__ = fn.__name__
    return run
