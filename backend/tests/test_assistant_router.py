"""Contract checks for the assistant HTTP + WebSocket surface.

Drives the real FastAPI app with a fake agent and stubbed persistence -- no LLM, no
databases. What it protects is the handshake with the frontend, where a mistake is
invisible rather than loud:

  * The WS lives at /ws/assistant/{run_id}, NOT under /api/v1. The client strips the
    prefix itself (buildAssistantWsUrl), so a prefixed mount is simply never dialled.
  * The client POSTs and only THEN connects. Without replay, the opening events -- and for
    a fast run, the whole answer -- are gone before anyone is listening.
  * The stream must always end in done/error. The client has no onclose handler.

Run: python backend/tests/test_assistant_router.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from app.assistant import bus, persistence, service  # noqa: E402
from app.routers import assistant as assistant_router  # noqa: E402


class _FakeAgent:
    def __init__(self, script):
        self._script = script

    async def astream(self, _inputs, config=None, stream_mode=None):
        for update in self._script:
            yield update


def _install_fakes(script) -> dict[str, Any]:
    """Stub the database out; keep the router, bus and service real."""
    saved: dict[str, Any] = {"messages": [], "artifacts": []}

    # The fake agent models the react `astream` shape, so drive the single-loop path; the
    # graph path has its own coverage. settings is frozen, so poke via object.__setattr__.
    object.__setattr__(service.settings, "assistant_multi_agent", False)
    service.build_agent = lambda **_: _FakeAgent(script)  # type: ignore[assignment]
    assistant_router._resolve_case_context = lambda case_id, crime_no: (  # type: ignore[assignment]
        {"case_id": 1000001, "crime_no": "129011001202600001"} if (case_id or crime_no) else None
    )
    persistence.ensure_session = lambda sid, uid, title, case_id, lang: sid or "sess-test"  # type: ignore[assignment]
    persistence.load_history = lambda sid, limit=20: []  # type: ignore[assignment]
    persistence.load_memories = lambda uid, limit=20: []  # type: ignore[assignment]
    persistence.save_message = lambda *a, **k: saved["messages"].append((a, k))  # type: ignore[assignment]
    persistence.persist_run_artifacts = lambda *a, **k: None  # type: ignore[assignment]
    persistence.build_memory_tool = lambda uid, rid: None  # type: ignore[assignment]
    assistant_router.build_report_tool = lambda *a, **k: None  # type: ignore[assignment]
    # build_agent is faked, so the None tools above are never bound.
    return saved


def _answer(frames: list[dict]) -> str:
    return "".join(f["delta"] for f in frames if f["type"] == "answer_delta")


class TestMessageAndStream(unittest.TestCase):
    def setUp(self):
        bus._history.clear()
        bus._subscribers.clear()
        bus._finished_at.clear()
        _prev = service.settings.assistant_multi_agent
        self.addCleanup(lambda: object.__setattr__(service.settings, "assistant_multi_agent", _prev))
        self.saved = _install_fakes([
            {"agent": {"messages": [AIMessage(content="Rs 9.3 lakh is still freezable.")]}},
        ])

    def test_post_returns_run_and_session_ids(self):
        with TestClient(_app()) as client:
            r = client.post("/api/v1/assistant/message",
                            json={"prompt": "where did the money go?", "language": "en"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["run_id"])
        self.assertTrue(body["session_id"])

    def test_ws_replays_events_emitted_before_it_connected(self):
        # The real ordering: POST (run starts emitting), THEN connect.
        with TestClient(_app()) as client:
            run_id = client.post("/api/v1/assistant/message",
                                 json={"prompt": "trace it", "language": "en"}).json()["run_id"]
            frames = []
            with client.websocket_connect(f"/ws/assistant/{run_id}") as ws:
                while True:
                    frame = ws.receive_json()
                    frames.append(frame)
                    if frame["type"] in ("done", "error"):
                        break

        types = [f["type"] for f in frames]
        self.assertEqual(types[0], "run_started")   # replayed, not lost
        self.assertEqual(types[-1], "done")         # always terminal
        self.assertIn("freezable", _answer(frames))

    def test_ws_is_not_mounted_under_the_api_prefix(self):
        # The client dials the bare path; a prefixed mount would never be reached.
        with TestClient(_app()) as client:
            run_id = client.post("/api/v1/assistant/message",
                                 json={"prompt": "x"}).json()["run_id"]
            with self.assertRaises(Exception):
                with client.websocket_connect(f"/api/v1/ws/assistant/{run_id}"):
                    pass

    def test_case_context_is_resolved_and_passed(self):
        with TestClient(_app()) as client:
            r = client.post("/api/v1/assistant/message",
                            json={"prompt": "summarise", "crime_no": "129011001202600001"})
        self.assertEqual(r.status_code, 200)

    def test_language_is_accepted_and_validated(self):
        with TestClient(_app()) as client:
            for lang in ("en", "hi", "kn"):
                r = client.post("/api/v1/assistant/message", json={"prompt": "x", "language": lang})
                self.assertEqual(r.status_code, 200, lang)
            bad = client.post("/api/v1/assistant/message", json={"prompt": "x", "language": "fr"})
            self.assertEqual(bad.status_code, 422)

    def test_empty_prompt_is_rejected(self):
        with TestClient(_app()) as client:
            self.assertEqual(
                client.post("/api/v1/assistant/message", json={"prompt": ""}).status_code, 422)


class TestCancelAndArtifacts(unittest.TestCase):
    def setUp(self):
        bus._history.clear()
        bus._subscribers.clear()
        bus._finished_at.clear()
        _prev = service.settings.assistant_multi_agent
        self.addCleanup(lambda: object.__setattr__(service.settings, "assistant_multi_agent", _prev))
        _install_fakes([{"agent": {"messages": [AIMessage(content="done")]}}])

    def test_cancel_unknown_run_reports_false_not_error(self):
        with TestClient(_app()) as client:
            r = client.post("/api/v1/assistant/runs/nope/cancel")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["cancelled"])

    def test_unknown_artifact_is_404(self):
        persistence.load_artifact = lambda aid: None  # type: ignore[assignment]
        with TestClient(_app()) as client:
            self.assertEqual(client.get("/api/v1/assistant/artifacts/nope").status_code, 404)

    def test_pdf_artifact_is_served_as_pdf_bytes(self):
        # DocumentArtifactView iframes this URL; the content type is what makes it render
        # instead of download as junk.
        persistence.load_artifact = lambda aid: {  # type: ignore[assignment]
            "artifact_id": aid, "kind": "document", "title": "Dossier",
            "stratus_key": None, "body": None, "blob": b"%PDF-1.4 fake",
        }
        with TestClient(_app()) as client:
            r = client.get("/api/v1/assistant/artifacts/doc-1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_png_artifact_is_served_as_image_bytes(self):
        persistence.load_artifact = lambda aid: {  # type: ignore[assignment]
            "artifact_id": aid, "kind": "document", "title": "Chart",
            "stratus_key": None, "body": {"format": "png"}, "blob": b"\x89PNG\r\n",
        }
        with TestClient(_app()) as client:
            r = client.get("/api/v1/assistant/artifacts/doc-2")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/png")
        self.assertTrue(r.content.startswith(b"\x89PNG"))

    def test_json_artifact_falls_back_to_the_inline_body(self):
        persistence.load_artifact = lambda aid: {  # type: ignore[assignment]
            "artifact_id": aid, "kind": "table", "title": "T",
            "stratus_key": None, "blob": None,
            "body": {"kind": "table", "id": aid, "title": "T", "columns": ["a"], "rows": [[1]]},
        }
        with TestClient(_app()) as client:
            r = client.get("/api/v1/assistant/artifacts/tbl-1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["kind"], "table")


def _app():
    """Build the app AFTER the fakes are installed (startup checks the DB otherwise)."""
    from fastapi import FastAPI

    from app.config import settings

    app = FastAPI()
    app.include_router(assistant_router.router, prefix=settings.api_prefix)
    app.include_router(assistant_router.ws_router)
    return app


if __name__ == "__main__":
    unittest.main(verbosity=2)
