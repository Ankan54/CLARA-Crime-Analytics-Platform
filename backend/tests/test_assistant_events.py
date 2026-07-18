"""Checks for the assistant wire contract + event bus.

Guards the two things that fail *silently* in the browser rather than raising:
  1. Casing. Frames are snake_case, nested payloads camelCase. Get it wrong and the UI
     reducer reads undefined and renders nothing -- no error anywhere.
  2. Thread-safe emit. Tools run in worker threads; publishing straight to an
     asyncio.Queue from one is undefined behaviour that usually *looks* fine locally.

Run: python -m unittest discover -s backend/tests -t backend
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assistant import bus  # noqa: E402
from app.assistant.emitter import RunEmitter  # noqa: E402
from app.assistant.events import (  # noqa: E402
    AssistantStep,
    GraphArtifact,
    GraphArtifactLink,
    GraphArtifactNode,
    StepEvent,
    TableArtifact,
    to_wire,
)


class TestWireCasing(unittest.TestCase):
    def test_frame_is_snake_case_but_step_is_camel(self):
        wire = to_wire(StepEvent(
            run_id="run-1",
            step=AssistantStep(
                id="sql-1", agent="sql", kind="tool_call", title="Counting cases",
                status="running", artifact_refs=["a1"],
            ),
        ))
        # Frame level: snake_case.
        self.assertEqual(wire["type"], "step")
        self.assertIn("run_id", wire)
        self.assertNotIn("runId", wire)
        # Nested: camelCase. This is the exact key AssistantPage reads.
        self.assertIn("artifactRefs", wire["step"])
        self.assertNotIn("artifact_refs", wire["step"])

    def test_optional_fields_omitted_not_null(self):
        wire = to_wire(StepEvent(
            run_id="r", step=AssistantStep(id="s", agent="graph", kind="thinking",
                                           title="t", status="done"),
        ))
        self.assertNotIn("detail", wire["step"])
        self.assertNotIn("artifactRefs", wire["step"])

    def test_rich_step_fields_are_camel_cased(self):
        wire = to_wire(StepEvent(
            run_id="r",
            step=AssistantStep(
                id="s", agent="graph", specialist="Financial Intelligence",
                kind="tool_call", title="Tracing", status="running",
                tool_name="trace_money_flow", tool_input={"case_ref": ""},
            ),
        ))
        self.assertEqual(wire["step"]["specialist"], "Financial Intelligence")
        self.assertEqual(wire["step"]["toolName"], "trace_money_flow")
        self.assertIn("toolInput", wire["step"])
        self.assertNotIn("tool_name", wire["step"])

    def test_artifact_discriminator_and_shape(self):
        wire = to_wire(StepEvent(run_id="r", step=AssistantStep(
            id="s", agent="graph", kind="tool_result", title="t", status="done")))
        self.assertEqual(wire["step"]["status"], "done")

        graph = GraphArtifact(
            id="g1", title="Money flow",
            nodes=[GraphArtifactNode(id="n1", label="A/c 5521", type="Account")],
            links=[GraphArtifactLink(source="n1", target="n1", relationship="TRANSACTED_WITH")],
        )
        dumped = graph.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(dumped["kind"], "graph")
        # GraphArtifactView keys node colour off `type`.
        self.assertEqual(dumped["nodes"][0]["type"], "Account")

        table = TableArtifact(id="t1", title="Cases", columns=["a"], rows=[[1], [None]])
        self.assertEqual(table.model_dump()["rows"][1][0], None)


class TestBusReplay(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bus._history.clear()
        bus._subscribers.clear()
        bus._finished_at.clear()

    async def test_replay_covers_post_then_connect_race(self):
        # The real ordering: the agent emits before the WS ever attaches.
        bus.publish("r1", {"type": "run_started", "run_id": "r1"})
        bus.publish("r1", {"type": "answer_delta", "run_id": "r1", "delta": "hi"})

        queue, replay = bus.subscribe("r1")
        self.assertEqual([e["type"] for e in replay], ["run_started", "answer_delta"])

        bus.publish("r1", {"type": "done", "run_id": "r1"})
        self.assertEqual((await queue.get())["type"], "done")
        self.assertTrue(bus.is_finished("r1"))

    async def test_two_subscribers_both_get_events(self):
        q1, _ = bus.subscribe("r2")
        q2, _ = bus.subscribe("r2")
        bus.publish("r2", {"type": "done", "run_id": "r2"})
        self.assertEqual((await q1.get())["type"], "done")
        self.assertEqual((await q2.get())["type"], "done")

    async def test_unsubscribe_stops_delivery(self):
        q, _ = bus.subscribe("r3")
        bus.unsubscribe("r3", q)
        bus.publish("r3", {"type": "done", "run_id": "r3"})
        self.assertTrue(q.empty())

    async def test_sweep_drops_history_only_after_retention(self):
        bus.publish("r4", {"type": "done", "run_id": "r4"})
        self.assertIn("r4", bus._history)  # still replayable right after finishing
        bus._finished_at["r4"] = -bus.RETENTION_SECONDS * 2
        bus.publish("r5", {"type": "done", "run_id": "r5"})  # any terminal event sweeps
        self.assertNotIn("r4", bus._history)


class TestEmitterThreading(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bus._history.clear()
        bus._subscribers.clear()
        bus._finished_at.clear()

    async def test_step_context_emits_running_then_done_with_same_id(self):
        emitter = RunEmitter("r6")
        with emitter.step("sql", "tool_call", "Counting") as handle:
            handle.output = "62 cases"
        await asyncio.sleep(0)  # let call_soon_threadsafe callbacks run

        steps = [e["step"] for e in bus._history["r6"] if e["type"] == "step"]
        self.assertEqual([s["status"] for s in steps], ["running", "done"])
        # Same id -> the UI upserts in place instead of showing two steps.
        self.assertEqual(steps[0]["id"], steps[1]["id"])
        self.assertEqual(steps[1]["output"], "62 cases")

    async def test_step_error_closes_step_and_reraises(self):
        emitter = RunEmitter("r7")
        with self.assertRaises(ValueError):
            with emitter.step("graph", "tool_call", "Tracing"):
                raise ValueError("neo4j exploded")
        await asyncio.sleep(0)

        steps = [e["step"] for e in bus._history["r7"] if e["type"] == "step"]
        # A step must never be left spinning: status closes as error, not running.
        self.assertEqual([s["status"] for s in steps], ["running", "error"])
        self.assertIn("neo4j exploded", steps[1]["output"])

    async def test_emit_from_worker_thread_is_safe_and_ordered(self):
        """The real tool path: emit from inside asyncio.to_thread."""
        emitter = RunEmitter("r8")

        def blocking_tool():  # runs off-loop, exactly like a Postgres/Neo4j call
            with emitter.step("vector", "tool_call", "Searching") as h:
                h.output = "3 matches"

        await asyncio.to_thread(blocking_tool)
        await asyncio.sleep(0)

        steps = [e["step"] for e in bus._history["r8"] if e["type"] == "step"]
        self.assertEqual([s["status"] for s in steps], ["running", "done"])

    async def test_artifact_via_handle_is_linked_to_its_step(self):
        emitter = RunEmitter("r9")
        with emitter.step("graph", "tool_call", "Linking") as h:
            h.emit_artifact(GraphArtifact(id="g9", title="Links", nodes=[], links=[]))
        await asyncio.sleep(0)

        types = [e["type"] for e in bus._history["r9"]]
        self.assertEqual(types, ["step", "artifact", "step"])
        done = [e["step"] for e in bus._history["r9"] if e["type"] == "step"][-1]
        self.assertEqual(done["artifactRefs"], ["g9"])


if __name__ == "__main__":
    unittest.main()
