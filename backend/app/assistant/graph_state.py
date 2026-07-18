"""The shared state for the assistant's LangGraph.

This is the "state management" of the multi-agent system: one typed channel bag that
every node in `graph.py` reads and writes, with an explicit reducer where two nodes can
write the same channel at once.

Only ONE channel needs a reducer -- `specialist_results`. It is the fan-in point: when the
supervisor fans out to several specialists in parallel (via `Send`), each specialist node
returns `{"specialist_results": [its_one_result]}` and they all land in the SAME superstep.
Without a reducer, LangGraph's default last-write-wins would keep only one specialist's
result and silently drop the rest (the classic map-reduce data-loss trap). `operator.add`
concatenates the per-branch lists into one, which is exactly the reduce step.

Every other channel is written by exactly one node per turn, so default replace-semantics
are correct and no reducer is declared (declaring one you don't need is just noise).

Per-branch inputs delivered through `Send` (`specialist_key`, `subtask`) are plain
last-write-wins channels: each parallel branch runs with its own isolated copy of the
state that `Send` handed it, so they never actually collide.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class SpecialistResult(TypedDict):
    """One specialist's finished contribution, collected at the fan-in."""

    key: str          # spec.key, e.g. "financial"
    display: str      # spec.display, e.g. "Financial Intelligence"
    agent: str        # spec.agent (sql|graph|vector|legal) -> UI colour
    subtask: str      # what this specialist was actually asked
    text: str         # the specialist's final finding


class AssistantState(TypedDict, total=False):
    # --- turn inputs (set once at START, read-only thereafter) ---------------
    question: str
    # NOTE: the session's prior turns are NOT a state channel. They are baked into the
    # graph's closures at build time (build_assistant_graph(history=...)), loaded fresh from
    # Postgres each turn by the router. Keeping them out of the flowing state means the
    # planner and every specialist see the same conversation without it riding through every
    # superstep. See build_assistant_graph's docstring.

    # --- supervisor output ---------------------------------------------------
    plan: list[dict[str, Any]]         # [{key, display, agent, subtask}, ...]
    direct_answer: str | None          # set for identity/refuse (guardrail bypass)

    # --- per-branch input, delivered via Send (NOT reduced) ------------------
    plan: list[dict[str, Any]]         # [{key, display, agent, subtask}, ...]

    # --- per-branch input, delivered via Send (NOT reduced) ------------------
    specialist_key: str
    subtask: str

    # --- fan-in accumulator: parallel specialists append here ----------------
    specialist_results: Annotated[list[SpecialistResult], operator.add]

    # --- final ---------------------------------------------------------------
    final_answer: str
