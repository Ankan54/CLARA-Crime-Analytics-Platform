"""The specialist sub-agents -- each a self-contained LangGraph subgraph.

A specialist is NOT a `create_react_agent` black box. It is a hand-wired two-node
`StateGraph` (the canonical ReAct loop):

    reason  --tools_condition-->  tools  --> reason  --> ... --> END

`reason` is an LLM bound to this specialist's *own* small tool subset; `tools` is
LangGraph's prebuilt `ToolNode`, which runs whatever tool calls the model emitted and
feeds the results back. The loop runs on `MessagesState` -- its `messages` channel carries
the `add_messages` reducer, so the growing reason/act transcript merges correctly without
us managing the list by hand.

Each compiled subgraph is used as a *node* in the parent supervisor graph (`graph.py`),
through a thin wrapper that translates the parent's `AssistantState` into this subgraph's
`MessagesState` and back -- the documented way to compose subgraphs that use a different
state schema.

The split between specialists is by investigative *purpose*, not by database: several
specialists share the same underlying tools (e.g. the graph tools live in both Financial
and Network) but wear different prompts and guardrails, so a shared tool shows up under the
right specialist label in the reasoning trail.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from ..llm import build_llm_pair
from .emitter import RunEmitter
from .tools import CURRENT_EMITTER, CURRENT_SPECIALIST, build_tools

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpecialistSpec:
    key: str
    display: str
    agent: str
    description: str
    tools: frozenset[str]
    prompt: str


COMMON_RULES = """Rules:
- Use tools and skills only; never invent facts.
- Return concise findings with the exact identifiers, dates, amounts and case refs the tools returned.
- Say when evidence is only an investigative lead, not proof of guilt.
- If a tool returns nothing, say what is missing instead of guessing.
"""


SPECS: tuple[SpecialistSpec, ...] = (
    SpecialistSpec(
        key="case",
        display="Case Analyst",
        agent="sql",
        description=(
            "Summarise one case, reconstruct the FIR timeline, list parties, charges and "
            "evidence on file. Use for case briefing, timeline, FIR summary, or when the "
            "officer asks what this case is about."
        ),
        tools=frozenset({"get_case_summary", "run_sql_select"}),
        prompt=COMMON_RULES + "\nFocus: build a clear one-case dossier from SQL facts.",
    ),
    SpecialistSpec(
        key="financial",
        display="Financial Intelligence",
        agent="graph",
        description=(
            "Trace cyber-fraud money movement, laundering velocity, freezable funds, mule "
            "accounts and crypto cash-out. Use for where the money went, how fast it moved, "
            "what can be frozen, layering, dormancy or PMLA money-trail questions."
        ),
        tools=frozenset({"trace_money_flow", "expand_entity"}),
        prompt=COMMON_RULES + (
            "\nFocus: lead with freezable funds, then total moved, speed, hops and cash-out. "
            "If a case is in context and no account number is supplied, call trace_money_flow(case_ref=\"\") immediately; "
            "do not ask the officer for a case reference you already have."
        ),
    ),
    SpecialistSpec(
        key="network",
        display="Network & Identity",
        agent="graph",
        description=(
            "Resolve aliases, inspect shared devices/UPIs/phones/accounts, find links between "
            "cases, show offender history and detect organised communities. Use for same "
            "person, repeat offender, find links, ring, gang, cluster or shared infrastructure."
        ),
        tools=frozenset({"person_history", "find_links_between_cases", "detect_community", "expand_entity", "run_cypher_read"}),
        prompt=COMMON_RULES + "\nFocus: explain the linking evidence and confidence; never call a link guilt.",
    ),
    SpecialistSpec(
        key="mo",
        display="MO & Trends",
        agent="vector",
        description=(
            "Find cases with the same modus operandi by narrative meaning and analyse trend or "
            "surge patterns. Use for similar cases, same script, MO match, emerging pattern, "
            "weekly/monthly trend, hotspot or cross-district spread questions."
        ),
        tools=frozenset({"find_similar_cases", "query_case_stats", "run_sql_select"}),
        prompt=COMMON_RULES + "\nFocus: report similarity scores, districts, dates and whether a pattern is cross-jurisdictional.",
    ),
    SpecialistSpec(
        key="legal",
        display="Legal",
        agent="legal",
        description=(
            "Check prosecutability through legal elements, evidence admissibility, BSA section "
            "63 gaps, PMLA predicate/proceeds checks and precedents. Use for charges, what must "
            "be proven, what's missing, weak points, acquittal risk or precedent questions."
        ),
        tools=frozenset({"legal_checklist", "find_precedents", "run_sql_select"}),
        prompt=COMMON_RULES + "\nFocus: checklist first; cite only precedents returned by tools.",
    ),
)

SPEC_BY_KEY: dict[str, SpecialistSpec] = {spec.key: spec for spec in SPECS}


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in content
            if isinstance(block, (str, dict))
        )
    return ""


def _strip_thinking_tags(text: str) -> str:
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", text or "", flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"</?thinking>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _bounded_history(history: list[Any] | None, *, turns: int = 4, max_chars: int = 1500) -> list[Any]:
    """The last few conversation messages, each truncated -- enough for a specialist to
    resolve "that account" / "the one you just found" without ballooning its context."""
    if not history:
        return []
    trimmed: list[Any] = []
    for message in history[-turns:]:
        text = _text_of(getattr(message, "content", ""))
        if not text:
            continue
        clipped = text if len(text) <= max_chars else text[:max_chars] + " ..."
        trimmed.append(message.__class__(content=clipped))
    return trimmed


def _system_prompt(
    spec: SpecialistSpec,
    language: str,
    case_context: dict[str, Any] | None,
    memories: list[str] | None,
) -> str:
    case = ""
    if case_context:
        case = (
            f"\nCase in context: {case_context.get('crime_no')} "
            f"(case_id={case_context.get('case_id')}). Empty case_ref means this case."
        )
    memory = "\n".join(f"- {m}" for m in (memories or []))
    if memory:
        memory = "\nOfficer memory (never override tool output):\n" + memory
    lang = "English" if language == "en" else ("Kannada" if language == "kn" else "Hindi")
    return f"{spec.prompt}{case}{memory}\nWrite the final specialist finding in {lang}."


def build_specialist_subgraph(
    spec: SpecialistSpec,
    *,
    language: str,
    case_context: dict[str, Any] | None,
    memories: list[str] | None,
    extra_tools: list[StructuredTool] | None = None,
):
    """Compile this specialist's ReAct subgraph (reason <-> tools loop)."""
    primary, fallback = build_llm_pair(purpose="conv_ai")
    tools = build_tools(tool_names=set(spec.tools), extra=extra_tools)
    model = primary.with_fallbacks([fallback]).bind_tools(tools)
    system = SystemMessage(content=_system_prompt(spec, language, case_context, memories))

    async def reason(state: MessagesState) -> dict[str, Any]:
        # The system message is prepended each turn rather than stored in the channel, so
        # the checkpointed transcript stays just the reason/act exchange.
        response = await model.ainvoke([system, *state["messages"]])
        return {"messages": [response]}

    sg = StateGraph(MessagesState)
    sg.add_node("reason", reason)
    sg.add_node("tools", ToolNode(tools))     # named "tools" so tools_condition routes here by default
    sg.add_edge(START, "reason")
    sg.add_conditional_edges("reason", tools_condition)   # -> "tools" if tool calls, else END
    sg.add_edge("tools", "reason")
    return sg.compile(name=f"{spec.key}_specialist")


async def run_specialist(
    spec: SpecialistSpec,
    subtask: str,
    *,
    language: str,
    case_context: dict[str, Any] | None,
    memories: list[str] | None,
    extra_tools: list[StructuredTool] | None = None,
    history: list[Any] | None = None,
    recursion_limit: int,
) -> str:
    """Run one specialist subgraph to its final finding.

    `history` is the recent conversation of this session; prepending it before the subtask
    makes the specialist context-aware, so a follow-up ("expand on that account") still
    resolves even if the planner's subtask is terse. Streams the subgraph so the model's
    between-tool reasoning becomes labelled "thinking" steps in the trail; the tool calls
    themselves emit their own steps from inside the tool bodies (they read
    CURRENT_SPECIALIST, set by the caller in graph.py).
    """
    emitter: RunEmitter | None = CURRENT_EMITTER.get()
    subgraph = build_specialist_subgraph(
        spec, language=language, case_context=case_context, memories=memories, extra_tools=extra_tools,
    )
    messages = [*_bounded_history(history), HumanMessage(content=subtask)]
    final = ""
    async for update in subgraph.astream(
        {"messages": messages},
        {"recursion_limit": recursion_limit},
        stream_mode="updates",
    ):
        for _node, payload in (update or {}).items():
            for message in (payload or {}).get("messages", []) or []:
                if not isinstance(message, AIMessage):
                    continue
                text = _strip_thinking_tags(_text_of(message.content))
                if getattr(message, "tool_calls", None):
                    if text and emitter:
                        emitter.step_once(
                            spec.agent, "thinking", f"{spec.display} planning",  # type: ignore[arg-type]
                            specialist=spec.display, detail=text[:600],
                        )
                elif text:
                    final = text
    return final or f"{spec.display} found no answer for that subtask."
