"""Run lifecycle: start a run, stream it, cancel it, persist it.

Two invariants everything else here serves:

  * A run ALWAYS terminates with `done` or `error`. The frontend has no onclose handler
    (assistantClient.ts), so a socket that just goes quiet leaves the UI busy forever
    with no way out. Every exit path emits a terminal frame.
  * The blocking work never touches the event loop. Tools hop to threads (tools.py);
    history/persistence do too, since db.py is synchronous SQLAlchemy.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from . import bus
from .agent import MAX_ITERATIONS, build_agent, build_history
from .emitter import RunEmitter
from .tools import CURRENT_CASE_ID, CURRENT_EMITTER
from ..config import settings

logger = logging.getLogger(__name__)

# run_id -> task, so /cancel can reach a run in flight.
RUNS: dict[str, asyncio.Task] = {}


def _text_of(content: Any) -> str:
    """Flatten LangChain content, which is a str for OpenAI-style providers and a list
    of typed blocks for Anthropic/Bedrock."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "".join(parts)
    return ""


def _strip_thinking_tags(text: str) -> str:
    """Some providers return literal <thinking> blocks as text; never show them."""
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", text or "", flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"</?thinking>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _looks_like_provider_block(text: str) -> bool:
    low = (text or "").lower()
    return "content filter" in low or "generated text has been blocked" in low


def _fallback_from_tool_outputs(run_id: str) -> str:
    findings: list[str] = []
    artifacts: list[str] = []
    for event in bus.history(run_id):
        if event.get("type") == "step":
            step = event.get("step") or {}
            output = step.get("output")
            title = step.get("title")
            if step.get("status") == "done" and output and title and not str(title).startswith("Delegating"):
                findings.append(f"{title}: {output}")
        elif event.get("type") == "artifact":
            artifact = event.get("artifact") or {}
            if artifact.get("title"):
                artifacts.append(str(artifact["title"]))
    if not findings and not artifacts:
        return "The tools completed, but the model provider blocked the final wording. Please inspect the reasoning trail and artifacts for the grounded results."
    lines = ["The model provider blocked the final wording, but the grounded tool results are:"]
    lines.extend(f"- {item}" for item in findings[:6])
    if artifacts:
        lines.append("Artifacts: " + ", ".join(artifacts[:6]))
    return "\n".join(lines)


async def _stream_agent(agent, inputs: dict[str, Any], emitter: RunEmitter, config: dict[str, Any]) -> str:
    """Run the agent to completion, then emit the final answer.

    Deliberately reads `updates`, not `messages`, even though `messages` would give
    token-by-token streaming. A ReAct loop emits several assistant messages and only the
    last -- the one with no tool calls -- is the answer; the earlier ones are the model
    reasoning about which tool to call. With `messages` you cannot tell them apart in
    time: Anthropic and Bedrock emit the prose BEFORE the tool_use block in the same
    message, so by the time a tool call reveals the message as reasoning, its text has
    already been streamed to the officer. That put "Let me check the money trail..." at
    the top of the answer (caught by test_reasoning_before_a_tool_call_is_not_leaked).

    So: let the loop finish, then emit the real answer word by word. The officer still
    watches the reasoning trail fill in live -- tools emit their own steps as they run --
    and the answer that arrives is the answer, not the model thinking aloud.
    """
    final_answer = ""

    async for update in agent.astream(inputs, config=config, stream_mode="updates"):
        for node, payload in (update or {}).items():
            for message in (payload or {}).get("messages", []) or []:
                if not isinstance(message, AIMessage):
                    continue
                text = _text_of(message.content).strip()
                if getattr(message, "tool_calls", None):
                    # Reasoning that preceded a tool call: belongs in the trail, where it
                    # explains the route taken, not in the answer body.
                    clean = _strip_thinking_tags(text)
                    if clean:
                        emitter.step_once(
                            "supervisor", "thinking", "Deciding what to check", detail=clean[:600],
                        )
                elif text:
                    final_answer = _strip_thinking_tags(text)

    if _looks_like_provider_block(final_answer):
        final_answer = _fallback_from_tool_outputs(emitter.run_id)

    for piece in _word_chunks(final_answer):
        emitter.answer_delta(piece)
        # Yield to the loop so frames actually leave the socket as they're produced
        # rather than arriving as one block after the coroutine finishes.
        await asyncio.sleep(0)

    return final_answer


async def _run_graph(graph, initial_state: dict[str, Any], config: dict[str, Any]) -> str:
    """Drive the supervisor graph to a final state.

    The graph's own nodes stream everything the officer sees -- the supervisor node emits
    the route + plan, each specialist emits its steps, and the synthesize node streams the
    answer text -- all out-of-band through the RunEmitter on the ContextVar. So here we
    just run it to completion and read the final answer back for persistence.
    """
    final_state = await graph.ainvoke(initial_state, config=config)
    return (final_state or {}).get("final_answer", "") or ""


def _word_chunks(text: str, per_chunk: int = 6) -> list[str]:
    """Split into small pieces so the answer renders progressively."""
    if not text:
        return []
    words = text.split(" ")
    return [
        " ".join(words[i:i + per_chunk]) + (" " if i + per_chunk < len(words) else "")
        for i in range(0, len(words), per_chunk)
    ]


async def run_assistant(
    *,
    run_id: str,
    session_id: str,
    prompt: str,
    case_context: dict[str, Any] | None = None,
    language: str = "en",
    history: list[dict[str, Any]] | None = None,
    memories: list[str] | None = None,
    extra_tools: list[Any] | None = None,
    on_complete: Any = None,
) -> str:
    """Execute one turn. Emits the full event stream; returns the final answer text."""
    emitter = RunEmitter(run_id)
    emitter.run_started()

    # Tools read these from context. asyncio.to_thread copies the context into the
    # worker thread, so they survive the hop into blocking tool bodies.
    CURRENT_EMITTER.set(emitter)
    CURRENT_CASE_ID.set((case_context or {}).get("case_id"))

    answer = ""
    try:
        # The session's prior turns make follow-ups stateful. For the graph they are baked
        # into the agent at build time (planner + every specialist see them); the ReAct
        # fallback still prepends them to the message list below.
        session_history = build_history(history or [])
        agent = build_agent(
            language=language, case_context=case_context, memories=memories,
            extra_tools=extra_tools, history=session_history,
        )
        meta = {"run_id": run_id, "session_id": session_id}

        if settings.assistant_multi_agent:
            # Supervisor graph: it emits its own route/plan steps and streams the answer
            # from the synthesize node. The parent graph is shallow (supervisor -> fan-out
            # -> synthesize), so the default recursion limit is ample; each specialist
            # subgraph carries its own deeper budget internally. History is already baked
            # into the graph, so only the fresh question rides in the state.
            answer = await _run_graph(
                agent,
                {"question": prompt},
                {"recursion_limit": 25, "metadata": meta},
            )
        else:
            emitter.step_once(
                "supervisor", "route", "Routing the question",
                detail=(f"Case {case_context.get('crime_no')} in context."
                        if case_context else "No case in context - answering across the corpus."),
                output="Answering",
            )
            messages = session_history + [HumanMessage(content=prompt)]
            # recursion_limit bounds the ReAct loop. LangGraph counts every node visit, so
            # an N-iteration cap is ~2N+1 steps; derived from MAX_ITERATIONS so they can't
            # drift apart.
            answer = await _stream_agent(
                agent, {"messages": messages}, emitter,
                {"recursion_limit": 2 * MAX_ITERATIONS + 1, "metadata": meta},
            )

        if not answer.strip():
            answer = ("I could not produce an answer for that. Try naming the case by its CrimeNo, "
                      "or ask for something more specific.")
            emitter.answer_delta(answer)

        emitter.done()
        logger.info("assistant: run complete run_id=%s chars=%d", run_id, len(answer))

    except asyncio.CancelledError:
        # The officer pressed Stop. Close the turn cleanly so the UI leaves its busy
        # state, persist what we have, then let the cancellation propagate.
        logger.info("assistant: run cancelled run_id=%s", run_id)
        emitter.answer_delta("\n\n_Stopped by officer._")
        emitter.done()
        answer = (answer or "") + "\n\n_Stopped by officer._"
        if on_complete:
            await _safe_complete(on_complete, run_id, answer, cancelled=True)
        raise

    except Exception as exc:
        logger.exception("assistant: run failed run_id=%s", run_id)
        # error carries a message the UI renders; without a terminal frame it would hang.
        emitter.error(f"{type(exc).__name__}: {exc}"[:300])
        if on_complete:
            await _safe_complete(on_complete, run_id, answer or "", failed=True)
        return answer

    if on_complete:
        await _safe_complete(on_complete, run_id, answer)
    return answer


async def _safe_complete(on_complete: Any, run_id: str, answer: str, **flags: Any) -> None:
    """Persistence must never turn a good answer into a failed run."""
    try:
        result = on_complete(run_id, answer, **flags)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        logger.exception("assistant: on_complete hook failed run_id=%s", run_id)


def start_run(**kwargs: Any) -> str:
    """Schedule a run and register it so it can be cancelled. Returns the run_id."""
    run_id = kwargs.pop("run_id", None) or f"run-{uuid.uuid4().hex[:12]}"

    async def _runner() -> None:
        try:
            await run_assistant(run_id=run_id, **kwargs)
        finally:
            RUNS.pop(run_id, None)

    # copy_context so CURRENT_EMITTER set inside the task can't leak into the request
    # handler's context (or another concurrent run's).
    task = asyncio.get_running_loop().create_task(
        _runner(), context=contextvars.copy_context()
    )
    RUNS[run_id] = task
    return run_id


def cancel_run(run_id: str) -> bool:
    """Cancel an in-flight run. Returns False if it isn't running (already finished)."""
    task = RUNS.get(run_id)
    if task is None or task.done():
        return False
    task.cancel()
    logger.info("assistant: cancel requested run_id=%s", run_id)
    return True
