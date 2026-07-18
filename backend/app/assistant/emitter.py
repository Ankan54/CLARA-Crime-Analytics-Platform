"""RunEmitter -- how the agent and its tools talk to the UI.

Thread-safety is the whole design constraint here. Every tool body runs in a worker
thread (asyncio.to_thread, because the Postgres/Neo4j/Pinecone clients are all
synchronous), but bus.publish() fans out to asyncio.Queues, which are NOT thread-safe:
calling put_nowait from a worker thread is undefined behaviour and can wedge the loop.
So an emit from a worker thread is marshalled back onto the loop; an emit already on the
loop thread publishes inline. See RunEmitter._emit for why the distinction matters.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from . import bus
from .events import (
    ActionEvent,
    AgentKind,
    AnswerDeltaEvent,
    ArtifactEvent,
    AssistantAction,
    AssistantArtifact,
    AssistantCitation,
    AssistantStep,
    CodeEvent,
    CodePayload,
    CitationEvent,
    DoneEvent,
    ErrorEvent,
    PlanEvent,
    PlanPayload,
    RetrievalEvent,
    RetrievalPayload,
    RunStartedEvent,
    StepEvent,
    StepKind,
    to_wire,
)

logger = logging.getLogger(__name__)


class StepHandle:
    """Mutable handle yielded by RunEmitter.step().

    Set .query/.output as the work proceeds; whatever they hold when the block exits is
    what the finished step reports. emit_artifact() also records the artifact id on the
    step, which is what links a reasoning step to its chip in the UI.
    """

    def __init__(self, step_id: str, emitter: "RunEmitter") -> None:
        self.id = step_id
        self._emitter = emitter
        self.query: str | None = None
        self.output: str | None = None
        self.detail: str | None = None
        self.tool_name: str | None = None
        self.tool_input: dict[str, Any] | None = None
        self.artifact_refs: list[str] = []

    def emit_artifact(self, artifact: AssistantArtifact) -> str:
        self._emitter.artifact(artifact)
        self.artifact_refs.append(artifact.id)
        return artifact.id


class RunEmitter:
    """Emits the wire contract for one run. Safe to call from any thread."""

    def __init__(self, run_id: str, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.run_id = run_id
        self._loop = loop or asyncio.get_running_loop()

    def _emit(self, event: Any) -> None:
        payload = to_wire(event)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None  # a worker thread: no loop of its own

        if running is self._loop:
            # Already on the loop thread (the agent itself). Publish inline: marshalling
            # would defer every event by a loop iteration for no benefit, and a terminal
            # `done` emitted as the run returns could be left un-run entirely.
            bus.publish(self.run_id, payload)
        else:
            # A tool body in a worker thread. asyncio.Queue is not thread-safe, so hand
            # the publish to the loop. Emits from one thread stay FIFO, so a step's
            # running/done pair and its artifacts keep their order.
            self._loop.call_soon_threadsafe(bus.publish, self.run_id, payload)

    # -- lifecycle ------------------------------------------------------------

    def run_started(self) -> None:
        self._emit(RunStartedEvent(run_id=self.run_id))

    def done(self) -> None:
        self._emit(DoneEvent(run_id=self.run_id))

    def error(self, message: str) -> None:
        self._emit(ErrorEvent(run_id=self.run_id, message=message))

    # -- steps ----------------------------------------------------------------

    def _emit_step(
        self,
        step_id: str,
        agent: AgentKind,
        kind: StepKind,
        title: str,
        status: str,
        *,
        detail: str | None = None,
        specialist: str | None = None,
        tool_name: str | None = None,
        tool_input: dict[str, Any] | None = None,
        query: str | None = None,
        output: str | None = None,
        artifact_refs: list[str] | None = None,
    ) -> None:
        self._emit(StepEvent(
            run_id=self.run_id,
            step=AssistantStep(
                id=step_id, agent=agent, kind=kind, title=title, status=status,  # type: ignore[arg-type]
                specialist=specialist,
                detail=detail, tool_name=tool_name, tool_input=tool_input,
                query=query, output=output,
                artifact_refs=artifact_refs or None,
            ),
        ))

    def step_once(
        self,
        agent: AgentKind,
        kind: StepKind,
        title: str,
        *,
        detail: str | None = None,
        specialist: str | None = None,
        output: str | None = None,
    ) -> None:
        """Emit a single already-finished step.

        For work that is complete by the time we can describe it -- the model's own
        reasoning, which is only identifiable as reasoning once the tool call it precedes
        has arrived. A running->done pair would be a lie there.
        """
        self._emit_step(
            f"{agent}-{uuid.uuid4().hex[:8]}", agent, kind, title, "done",
            detail=detail, specialist=specialist, output=output,
        )

    @contextmanager
    def step(
        self,
        agent: AgentKind,
        kind: StepKind = "tool_call",
        title: str = "",
        *,
        detail: str | None = None,
        specialist: str | None = None,
        tool_name: str | None = None,
        tool_input: dict[str, Any] | None = None,
        query: str | None = None,
    ) -> Iterator[StepHandle]:
        """Emit a running step, run the block, then close it out as done or error.

        The UI upserts steps by id (AssistantPage::applyEvent), so both emits reuse the
        same id and the step transitions in place instead of duplicating.

        An exception closes the step as 'error' and re-raises: the agent still sees the
        failure and can recover or explain it, but the UI never keeps a step spinning
        forever -- which is what a bare emit-running/emit-done pair does on any raise.
        """
        step_id = f"{agent}-{uuid.uuid4().hex[:8]}"
        handle = StepHandle(step_id, self)
        handle.query = query
        handle.detail = detail
        handle.tool_name = tool_name
        handle.tool_input = tool_input
        self._emit_step(
            step_id, agent, kind, title, "running",
            detail=detail, specialist=specialist,
            tool_name=tool_name, tool_input=tool_input, query=query,
        )
        try:
            yield handle
        except Exception as exc:
            logger.exception("assistant step failed run_id=%s step=%s", self.run_id, title)
            self._emit_step(
                step_id, agent, kind, title, "error",
                detail=handle.detail, specialist=specialist,
                tool_name=handle.tool_name, tool_input=handle.tool_input, query=handle.query,
                output=f"{type(exc).__name__}: {exc}"[:300],
                artifact_refs=handle.artifact_refs,
            )
            raise
        else:
            self._emit_step(
                step_id, agent, kind, title, "done",
                detail=handle.detail, specialist=specialist,
                tool_name=handle.tool_name, tool_input=handle.tool_input,
                query=handle.query, output=handle.output,
                artifact_refs=handle.artifact_refs,
            )

    # -- payloads -------------------------------------------------------------

    def answer_delta(self, delta: str) -> None:
        if delta:
            self._emit(AnswerDeltaEvent(run_id=self.run_id, delta=delta))

    def artifact(self, artifact: AssistantArtifact) -> None:
        self._emit(ArtifactEvent(run_id=self.run_id, artifact=artifact))

    def retrieval(self, retrieval: RetrievalPayload) -> None:
        self._emit(RetrievalEvent(run_id=self.run_id, retrieval=retrieval))

    def code(self, code: CodePayload) -> None:
        self._emit(CodeEvent(run_id=self.run_id, code=code))

    def plan(self, plan: PlanPayload) -> None:
        self._emit(PlanEvent(run_id=self.run_id, plan=plan))

    def citation(self, citation: AssistantCitation) -> None:
        self._emit(CitationEvent(run_id=self.run_id, citation=citation))

    def action(self, action: AssistantAction) -> None:
        self._emit(ActionEvent(run_id=self.run_id, action=action))
