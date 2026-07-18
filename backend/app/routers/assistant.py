"""Assistant API: start a run, stream it, stop it, replay it.

Path shapes are dictated by the frontend and are not free choices:
  * POST goes under settings.api_prefix, because assistantClient.ts posts to
    `${API_BASE}/assistant/message` where API_BASE already ends in /api/v1.
  * The WebSocket is mounted with NO prefix -- buildAssistantWsUrl() strips a trailing
    /api/v1 before appending /ws/assistant/{run_id}.

The POST returns as soon as the run is scheduled; the client then opens the socket. That
ordering is why bus.subscribe() hands back a replay of everything already emitted.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..assistant import bus, persistence, service
from ..assistant.events import AssistantLanguage
from ..assistant.skills.analysis import build_python_tool
from ..assistant.skills.report import build_report_tool
from ..config import settings
from ..db import db_session

logger = logging.getLogger(__name__)

_ARTIFACT_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "svg": "image/svg+xml",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "html": "text/html; charset=utf-8",
    "text": "text/plain; charset=utf-8",
}

# Two routers because the two surfaces live at different roots: `router` is mounted under
# settings.api_prefix, `ws_router` at the bare root. Mounting the socket under /api/v1
# would put it at a path the client never dials.
router = APIRouter(tags=["assistant"])
ws_router = APIRouter(tags=["assistant"])

# Generous on purpose. Nothing is emitted DURING an LLM call -- only tool steps stream --
# so a single slow generation (cold start, long final answer in Kannada) is legitimately
# silent for a while. Time out too eagerly and we send a spurious `error` to the officer
# while the real `done` arrives to nobody. This only needs to be short enough to eventually
# release a socket whose run died without a terminal frame.
WS_IDLE_TIMEOUT_SECONDS = 240.0


class AssistantMessageRequest(BaseModel):
    prompt: str = Field(min_length=1)
    case_id: int | None = None
    crime_no: str | None = None
    scenario_key: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    language: AssistantLanguage = "en"


class AssistantMessageResponse(BaseModel):
    run_id: str
    session_id: str


def _resolve_case_context(case_id: int | None, crime_no: str | None) -> dict[str, Any] | None:
    """Turn whichever case reference the client sent into {case_id, crime_no}.

    The UI can supply either: a case_id from its picker, or a crime_no from a scenario.
    """
    if not case_id and not crime_no:
        return None
    with db_session() as db:
        if case_id:
            row = db.execute(text(
                "SELECT CaseMasterID AS case_id, CrimeNo AS crime_no FROM CaseMaster WHERE CaseMasterID = :v"
            ), {"v": case_id}).mappings().first()
        else:
            row = db.execute(text(
                "SELECT CaseMasterID AS case_id, CrimeNo AS crime_no FROM CaseMaster WHERE CrimeNo = :v"
            ), {"v": crime_no}).mappings().first()
    if not row:
        # Not fatal: the officer may be asking about a case that hasn't been ingested yet,
        # and the agent can still answer across the corpus.
        logger.info("assistant: unresolved case reference case_id=%s crime_no=%s", case_id, crime_no)
        return None
    return dict(row)


@router.post("/assistant/message", response_model=AssistantMessageResponse)
async def post_message(request: AssistantMessageRequest) -> AssistantMessageResponse:
    user_id = request.user_id or "demo-user"

    # All of this touches Postgres, which is synchronous -- keep it off the event loop.
    case_context = await asyncio.to_thread(_resolve_case_context, request.case_id, request.crime_no)
    session_id = await asyncio.to_thread(
        persistence.ensure_session, request.session_id, user_id,
        request.prompt[:120], (case_context or {}).get("case_id"), request.language,
    )
    history = await asyncio.to_thread(persistence.load_history, session_id)
    memories = await asyncio.to_thread(persistence.load_memories, user_id)

    await asyncio.to_thread(persistence.save_message, session_id, "user", request.prompt)

    run_id = f"run-{session_id[-6:]}-{len(history) + 1}-{abs(hash(request.prompt)) % 10000:04d}"

    def _on_complete(rid: str, answer: str, **flags: Any) -> None:
        """Persist the finished turn. Runs in the run's task, after the answer is out."""
        events = bus.history(rid)
        payload = {
            "steps": [e["step"] for e in events if e["type"] == "step"],
            "citations": [e["citation"] for e in events if e["type"] == "citation"],
            "actions": [e["action"] for e in events if e["type"] == "action"],
            "artifacts": [
                {k: v for k, v in e["artifact"].items() if k in ("id", "kind", "title", "caption", "url")}
                for e in events if e["type"] == "artifact"
            ],
            **flags,
        }
        persistence.save_message(session_id, "assistant", answer, run_id=rid, payload=payload)
        persistence.persist_run_artifacts(session_id, rid, events)

    async def _on_complete_async(rid: str, answer: str, **flags: Any) -> None:
        await asyncio.to_thread(lambda: _on_complete(rid, answer, **flags))

    officer = f"{user_id}"
    service.start_run(
        run_id=run_id,
        session_id=session_id,
        prompt=request.prompt,
        case_context=case_context,
        language=request.language,
        history=history,
        memories=memories,
        extra_tools=[
            persistence.build_memory_tool(user_id, run_id),
            build_python_tool(session_id, run_id),
            build_report_tool(session_id, run_id, request.language, officer,
                              case_ref=(case_context or {}).get("crime_no", "")),
        ],
        on_complete=_on_complete_async,
    )
    logger.info("assistant: run started run_id=%s session=%s lang=%s case=%s",
                run_id, session_id, request.language, (case_context or {}).get("crime_no"))
    return AssistantMessageResponse(run_id=run_id, session_id=session_id)


@ws_router.websocket("/ws/assistant/{run_id}")
async def stream_run(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    queue, replay = bus.subscribe(run_id)
    try:
        # Replay first: the client POSTs and only then connects, so the opening events
        # (and for a fast run, the entire answer) are already in the past.
        for event in replay:
            await websocket.send_json(event)
        if any(e.get("type") in ("done", "error") for e in replay):
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=WS_IDLE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                # Never leave the UI spinning: it has no onclose handler, so a socket that
                # simply goes quiet is a permanently-stuck screen.
                logger.warning("assistant: ws idle timeout run_id=%s", run_id)
                await websocket.send_json({
                    "type": "error", "run_id": run_id,
                    "message": "The assistant stopped responding. Please try again.",
                })
                return
            await websocket.send_json(event)
            if event.get("type") in ("done", "error"):
                return
    except WebSocketDisconnect:
        logger.info("assistant: ws disconnected run_id=%s", run_id)
    except Exception:
        logger.exception("assistant: ws error run_id=%s", run_id)
    finally:
        bus.unsubscribe(run_id, queue)


@router.post("/assistant/runs/{run_id}/cancel")
async def cancel(run_id: str) -> dict[str, Any]:
    """Stop a run. The run still terminates through its normal `done` frame, so the UI
    needs no special handling."""
    cancelled = service.cancel_run(run_id)
    return {"run_id": run_id, "cancelled": cancelled}


@router.get("/assistant/sessions")
async def get_sessions(user_id: str = "demo-user") -> dict[str, Any]:
    sessions = await asyncio.to_thread(persistence.list_sessions, user_id)
    return {"sessions": sessions}


@router.get("/assistant/sessions/{session_id}/messages")
async def get_messages(session_id: str) -> dict[str, Any]:
    messages = await asyncio.to_thread(persistence.load_history, session_id, 200)
    return {"session_id": session_id, "messages": messages}


@router.get("/assistant/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str) -> Response:
    """Serve an artifact body.

    PDFs come back as bytes (DocumentArtifactView iframes this URL); everything else is
    the JSON the UI already knows how to render.
    """
    row = await asyncio.to_thread(persistence.load_artifact, artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Unknown artifact {artifact_id}")

    if row["kind"] == "document" and row.get("blob"):
        body = row.get("body") or {}
        fmt = (body.get("format") or "pdf").lower() if isinstance(body, dict) else "pdf"
        return Response(
            content=bytes(row["blob"]), media_type=_ARTIFACT_MEDIA_TYPES.get(fmt, "application/octet-stream"),
            headers={"Content-Disposition": f'inline; filename="{artifact_id}.{fmt}"'},
        )
    if row.get("stratus_key"):
        try:
            from ..services.catalyst_queue import get_object_text

            text_body = await asyncio.to_thread(get_object_text, row["stratus_key"])
            return Response(content=text_body, media_type="application/json")
        except Exception:
            logger.exception("assistant: Stratus read failed for %s", row["stratus_key"])
    if row.get("body"):
        return JSONResponse(content=row["body"])
    raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} has no stored body")
