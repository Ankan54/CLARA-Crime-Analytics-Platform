"""Checks for the run lifecycle.

Drives run_assistant with a fake chat model and fake tools -- no LLM, no databases -- so
the parts that are easy to get wrong and expensive to discover live are pinned down:

  * A run ALWAYS ends with done/error. The frontend has no onclose handler, so a missing
    terminal frame is a permanently-hung UI, not a visible failure.
  * Reasoning that precedes a tool call is NOT leaked into the answer body.
  * Cancellation still closes the turn cleanly.

Run: python backend/tests/test_assistant_service.py
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage  # noqa: E402

from app.assistant import bus, service  # noqa: E402
from app.assistant.agent import build_system_prompt  # noqa: E402


class _FakeAgent:
    """Stands in for the compiled ReAct graph, emitting the `updates` shape LangGraph does:
    {node_name: {"messages": [...]}} per super-step."""

    def __init__(self, script: list[Any]):
        self._script = script

    async def astream(self, _inputs, config=None, stream_mode=None):
        for update in self._script:
            await asyncio.sleep(0)
            yield update


def _agent_says(text: str) -> dict:
    """A final assistant message: content, no tool calls."""
    return {"agent": {"messages": [AIMessage(content=text)]}}


def _agent_calls_tool(text: str = "") -> dict:
    """An assistant message that reasons then calls a tool -- the Anthropic/Bedrock shape."""
    return {"agent": {"messages": [AIMessage(
        content=text,
        tool_calls=[{"name": "get_case_summary", "args": {}, "id": "tc1", "type": "tool_call"}],
    )]}}


def _events(run_id: str) -> list[dict]:
    return bus._history.get(run_id, [])


def _types(run_id: str) -> list[str]:
    return [e["type"] for e in _events(run_id)]


def _answer(run_id: str) -> str:
    return "".join(e["delta"] for e in _events(run_id) if e["type"] == "answer_delta")


class TestStreaming(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bus._history.clear()
        bus._subscribers.clear()
        bus._finished_at.clear()
        # These pin down the single-loop `_stream_agent` behaviour (updates streaming,
        # reasoning-not-leaked). The graph path is covered separately (TestGraphPath +
        # test_assistant_playbooks_and_code), so drive the react fallback here. settings is
        # a frozen dataclass, so poke the flag via object.__setattr__.
        self._prev_multi = service.settings.assistant_multi_agent
        object.__setattr__(service.settings, "assistant_multi_agent", False)
        self.addCleanup(lambda: object.__setattr__(service.settings, "assistant_multi_agent", self._prev_multi))

    async def _run(self, script, **kw):
        agent = _FakeAgent(script)
        service.build_agent = lambda **_: agent  # type: ignore[assignment]
        return await service.run_assistant(
            run_id=kw.pop("run_id", "r1"), session_id="s1", prompt="where did the money go?", **kw
        )

    async def test_plain_answer_streams_and_terminates(self):
        answer = await self._run([_agent_says("The money went to A/c 5521.")])
        self.assertEqual(answer, "The money went to A/c 5521.")
        # Emitted progressively, but reassembling the deltas must give back the answer.
        self.assertEqual(_answer("r1"), "The money went to A/c 5521.")
        self.assertGreater(len([e for e in _events("r1") if e["type"] == "answer_delta"]), 0)
        types = _types("r1")
        self.assertEqual(types[0], "run_started")
        self.assertEqual(types[-1], "done")  # terminal frame is non-negotiable

    async def test_reasoning_before_a_tool_call_is_not_leaked_into_the_answer(self):
        # Anthropic/Bedrock put prose BEFORE the tool_use block in the same message. That
        # prose is reasoning; if it reaches the answer the officer reads the model
        # thinking aloud instead of a finding. This is why we stream `updates`.
        await self._run([
            _agent_calls_tool("Let me check the money trail."),
            _agent_says("Rs 9.3 lakh is still freezable."),
        ])
        self.assertEqual(_answer("r1"), "Rs 9.3 lakh is still freezable.")
        self.assertNotIn("Let me check", _answer("r1"))
        # ...but it is not discarded: it shows up in the reasoning trail.
        thinking = [e["step"] for e in _events("r1") if e["type"] == "step" and e["step"]["kind"] == "thinking"]
        self.assertTrue(thinking)
        self.assertIn("Let me check", thinking[0]["detail"])

    async def test_last_message_wins_over_earlier_ones(self):
        await self._run([_agent_says("draft"), _agent_says("final answer")])
        self.assertEqual(_answer("r1"), "final answer")

    async def test_literal_thinking_tags_are_not_leaked(self):
        await self._run([_agent_says("<thinking>private chain</thinking>Final finding.")])
        self.assertEqual(_answer("r1"), "Final finding.")

    async def test_provider_content_filter_message_is_replaced(self):
        await self._run([_agent_says("The generated text has been blocked by our content filters.")])
        self.assertNotIn("content filters", _answer("r1"))
        self.assertIn("grounded tool results", _answer("r1"))

    async def test_empty_answer_still_says_something_and_terminates(self):
        answer = await self._run([_agent_calls_tool("")])
        self.assertTrue(answer.strip())
        self.assertEqual(_types("r1")[-1], "done")

    async def test_route_step_is_emitted_before_the_answer(self):
        await self._run([_agent_says("ok")])
        steps = [e["step"] for e in _events("r1") if e["type"] == "step"]
        self.assertEqual(steps[0]["kind"], "route")
        self.assertEqual(steps[0]["agent"], "supervisor")


class TestFailureAndCancel(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bus._history.clear()
        bus._subscribers.clear()
        bus._finished_at.clear()
        # Cancel/error/persist is shared lifecycle code; exercise it via the react fallback
        # whose fake agent models the astream shape.
        self._prev_multi = service.settings.assistant_multi_agent
        object.__setattr__(service.settings, "assistant_multi_agent", False)
        self.addCleanup(lambda: object.__setattr__(service.settings, "assistant_multi_agent", self._prev_multi))

    async def test_tool_explosion_ends_in_error_not_silence(self):
        class _Boom:
            async def astream(self, *_a, **_k):
                raise RuntimeError("neo4j unreachable")
                yield  # pragma: no cover

        service.build_agent = lambda **_: _Boom()  # type: ignore[assignment]
        await service.run_assistant(run_id="r2", session_id="s1", prompt="x")
        types = _types("r2")
        self.assertEqual(types[-1], "error")  # never a silent close
        err = [e for e in _events("r2") if e["type"] == "error"][0]
        self.assertIn("neo4j unreachable", err["message"])

    async def test_cancel_closes_the_turn_and_persists_partial(self):
        started = asyncio.Event()

        class _Slow:
            async def astream(self, *_a, **_k):
                yield _agent_calls_tool("Tracing the trail")
                started.set()
                await asyncio.sleep(30)  # cancellation lands here, between tool calls
                yield _agent_says("never")  # pragma: no cover

        service.build_agent = lambda **_: _Slow()  # type: ignore[assignment]
        saved: dict[str, Any] = {}

        async def _on_complete(run_id, answer, **flags):
            saved.update({"run_id": run_id, "answer": answer, **flags})

        run_id = service.start_run(
            run_id="r3", session_id="s1", prompt="trace it", on_complete=_on_complete,
        )
        await started.wait()
        self.assertTrue(service.cancel_run(run_id))
        with self.assertRaises(asyncio.CancelledError):
            await service.RUNS.get(run_id, asyncio.sleep(0))  # type: ignore[arg-type]

        await asyncio.sleep(0.05)
        # The UI must leave its busy state even on a stop.
        self.assertEqual(_types("r3")[-1], "done")
        self.assertIn("Stopped by officer", _answer("r3"))
        self.assertTrue(saved.get("cancelled"))
        self.assertNotIn("r3", service.RUNS)  # registry cleaned up

    async def test_cancel_unknown_run_is_false(self):
        self.assertFalse(service.cancel_run("nope"))


class TestGraphPath(unittest.IsolatedAsyncioTestCase):
    """The default multi-agent path: service drives the compiled supervisor graph via
    ainvoke, the graph streams the answer out-of-band through the emitter, and the run
    still terminates with `done`."""

    def setUp(self):
        bus._history.clear()
        bus._subscribers.clear()
        bus._finished_at.clear()
        self._prev_multi = service.settings.assistant_multi_agent
        object.__setattr__(service.settings, "assistant_multi_agent", True)
        self.addCleanup(lambda: object.__setattr__(service.settings, "assistant_multi_agent", self._prev_multi))

    async def test_graph_run_streams_answer_and_terminates(self):
        from app.assistant.tools import CURRENT_EMITTER

        class _FakeGraph:
            async def ainvoke(self, _state, config=None):
                # Stand in for the synthesize node: emit the answer, return final state.
                emitter = CURRENT_EMITTER.get()
                for piece in ("Rs 9.3 lakh ", "is still freezable."):
                    emitter.answer_delta(piece)
                return {"final_answer": "Rs 9.3 lakh is still freezable."}

        service.build_agent = lambda **_: _FakeGraph()  # type: ignore[assignment]
        answer = await service.run_assistant(run_id="g1", session_id="s1", prompt="trace it")
        self.assertEqual(answer, "Rs 9.3 lakh is still freezable.")
        self.assertIn("freezable", _answer("g1"))
        self.assertEqual(_types("g1")[-1], "done")


class TestPrompt(unittest.TestCase):
    def test_language_clause_is_mandatory_and_protects_identifiers(self):
        kn = build_system_prompt(language="kn")
        self.assertIn("Kannada", kn)
        self.assertIn("mandatory", kn)
        # Statutes/identifiers must survive translation verbatim or citations break.
        self.assertIn("BNS 318", kn)
        self.assertIn("never translated", kn)
        self.assertIn("English", build_system_prompt(language="en"))

    def test_case_and_memory_context_are_injected(self):
        prompt = build_system_prompt(
            case_context={"crime_no": "129011001202600001", "case_id": 42},
            memories=["prefers amounts in lakh"],
        )
        self.assertIn("129011001202600001", prompt)
        self.assertIn("prefers amounts in lakh", prompt)
        # Memory must not outrank live tool output.
        self.assertIn("never let it override", prompt)

    def test_grounding_rules_present(self):
        prompt = build_system_prompt()
        self.assertIn("Never invent a fact", prompt)
        self.assertIn("Decision support, not accusation", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
