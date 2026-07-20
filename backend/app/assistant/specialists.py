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

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from ..config import settings
from ..llm import build_llm_pair
from .emitter import RunEmitter
from .events import CodePayload
from .persona import NO_INTERNALS
from .schema_cards import GRAPH_SCHEMA_CARD, SCHEMA_BY_AGENT, SQL_SCHEMA_CARD, VECTOR_SCHEMA_CARD
from .tools import CURRENT_EMITTER, CURRENT_SPECIALIST, build_tools
from . import bus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpecialistSpec:
    key: str
    display: str
    agent: str
    description: str
    tools: frozenset[str]
    prompt: str
    friendly_action: str = ""  # human-friendly "what I'm doing" label for the UI trail


COMMON_RULES = f"""Rules:
- Use tools and skills only; never invent facts.
- If a `skill_*` tool's description matches the task, load it FIRST and follow its steps — it is the vetted workflow for exactly this question.
- Prefer the specific parameterised tool (get_case_summary, trace_money_flow, person_history, find_links_between_cases, detect_community, find_similar_cases, legal_checklist) over ad-hoc run_sql_select / run_cypher_read. Reach for the raw query tools only when no parameterised tool fits.
- Be decisive: once you have enough to answer, STOP and write the finding. Do NOT run many variations of the same query — 2-3 well-chosen tool calls is normal; looping past that means you should answer with what you have.
- Return concise findings with the exact identifiers, dates, amounts and case refs the tools returned.
- Say when evidence is only an investigative lead, not proof of guilt.
- If a tool returns nothing or errors, state plainly what is missing and suggest what the officer can try next instead of guessing.
- {NO_INTERNALS}
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
        friendly_action="Reviewing the case file",
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
        tools=frozenset({"trace_money_flow", "expand_entity", "run_sql_select", "run_cypher_read"}),
        prompt=COMMON_RULES + (
            "\nFocus: money movement. Pick the tool, call it, then STOP and write the finding:\n"
            "- 'where did the money go / trace / how fast / what is freezable / cash-out / layering / velocity' -> "
            "trace_money_flow(case_ref=\"\" for the case in context, or account_number=... for one account). It returns "
            "the WHOLE trail in ONE call: the money-flow graph, time-ordered transfers, freezable funds and any crypto "
            "cash-out. Lead with the freezable amount, then total moved, speed, hops, cash-out.\n"
            "- what one account/identifier connects to -> expand_entity(value).\n"
            "After trace_money_flow returns you ALREADY have the answer -- do NOT run confirming run_sql_select / "
            "run_cypher_read queries to re-verify the same trail. Reach for run_sql_select ONLY for a specific filter or "
            "aggregation trace_money_flow genuinely cannot produce (e.g. 'transfers above 5 lakh on 14 April'), then STOP.\n"
            "If a case is in context and no account number is supplied, call trace_money_flow(case_ref=\"\") immediately."
        ),
        friendly_action="Checking the money trail",
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
        prompt=COMMON_RULES + (
            "\nFocus: pick the RIGHT tool for the question, call it, then explain the linking evidence:\n"
            "- 'do we know this accused / other names / aliases / same person / repeat offender / his history / escalation' -> person_history(name). If you only have a case (not a name), FIRST get the name with one query: MATCH (c:CaseMaster {case_id:<id>})<-[:INVOLVES]-(a:Accused) RETURN a.display_name; then call person_history(that name). person_history collapses aliases via shared device/UPI/phone -- do NOT hand-write Cypher to resolve aliases yourself.\n"
            "- 'find links / are these cases connected / do they share an account-device-UPI' -> find_links_between_cases(case_refs). "
            "This is the graph-DB linkage step: it returns a Neo4j-backed graph (case nodes + the shared account/device/UPI as a labelled hub). "
            "Call it ONCE with all the case refs, then STOP and compose from its result: LEAD with that graph and a one-line "
            "'these N cases all share <identifier>'. Do NOT re-derive the links as an SQL table, and do NOT then call expand_entity or "
            "run_cypher_read on each shared identifier -- that one call already has the answer; looping over the identifiers just burns the "
            "step budget and produces nothing new.\n"
            "- 'organised ring / gang / community / cluster / is this surge organised' -> detect_community.\n"
            "- 'operator org chart / role map / who does what' -> load the operator-org-chart skill.\n"
            "- what one identifier connects to -> expand_entity(value).\n"
            "Use run_cypher_read ONLY for a graph question none of the above tools cover. Never call a link proof of guilt."
        ),
        friendly_action="Looking for links and shared identities",
    ),
    SpecialistSpec(
        key="mo",
        display="Patterns & Trends",
        agent="vector",
        description=(
            "Find cases with the same modus operandi by narrative meaning and analyse trend or "
            "surge patterns. Use for similar cases, same script, MO match, emerging pattern, "
            "weekly/monthly trend, hotspot or cross-district spread questions."
        ),
        tools=frozenset({"find_similar_cases", "query_case_stats", "run_sql_select"}),
        prompt=COMMON_RULES + (
            "\nFocus: pick the tool, call it, then STOP and report:\n"
            "- 'same MO / same script / similar cases / has this appeared elsewhere' -> find_similar_cases(case_ref=\"\" for the case in context). "
            "This is PURE vector similarity (it embeds the FIR narrative and cosine-ranks Pinecone). It returns the ranked matches with scores + districts in ONE call. "
            "Compose the finding as a STORY of similarity only: (1) one line naming the shared modus operandi / common script these cases follow, "
            "(2) the matched cases with their scores and districts, (3) whether it is cross-jurisdictional. Then STOP. "
            "CRITICAL: this answer must NOT contain link analysis. Do NOT run find_links_between_cases, run_cypher_read, detect_community, expand_entity or any "
            "shared-identifier / EXT_Mentions run_sql_select here, and do NOT load the find-links skill. Whether these cases actually SHARE an account/device/UPI "
            "is a DELIBERATELY SEPARATE next step the officer runs via the one-click 'Find links among these cases' follow-up the tool already emits -- "
            "answering it now would spoil that follow-up. End by inviting the officer to run that link check.\n"
            "- 'trend / surge / how many / which district / spike / hotspot / rising' -> query_case_stats "
            "(group_by district|crime_type|month, with a crime_type and/or date filter). One call gives the counts.\n"
            "Reach for run_sql_select ONLY for a specific count/filter query_case_stats cannot express, then STOP. "
            "State a 0.81 similarity as 'possible', 0.9+ as a strong match."
        ),
        friendly_action="Finding similar cases",
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
        friendly_action="Checking the legal position",
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


def _split_reasoning_and_answer(content: Any) -> tuple[str, str]:
    """Split an AIMessage's content into (reasoning_text, answer_text).

    Handles: Bedrock list-of-blocks (reasoning_content vs text), plain strings with
    inline <thinking>...</thinking> tags, and plain strings with no reasoning.
    """
    if isinstance(content, list):
        reasoning_parts: list[str] = []
        answer_parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "reasoning_content":
                    reasoning_parts.append(block.get("text", "") or block.get("content", ""))
                elif block.get("type") == "text":
                    answer_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    pass
                else:
                    answer_parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                answer_parts.append(block)
        return "".join(reasoning_parts), "".join(answer_parts)

    text = str(content or "")
    import re as _re
    thinking_match = _re.findall(r"<thinking>(.*?)</thinking>", text, flags=_re.IGNORECASE | _re.DOTALL)
    if thinking_match:
        reasoning = " ".join(thinking_match)
        answer = _re.sub(r"<thinking>.*?</thinking>", "", text, flags=_re.IGNORECASE | _re.DOTALL).strip()
        return reasoning, answer
    return "", text


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
    # A specialist needs the schema card for every store it can actually query, not just
    # its "home" store: the SQL escape hatch (run_sql_select) is useless without the SQL
    # card, and that is exactly what a stats/chart request leans on.
    cards: list[str] = []
    if "run_sql_select" in spec.tools or spec.agent in ("sql", "legal"):
        cards.append(SQL_SCHEMA_CARD)
    if "run_cypher_read" in spec.tools or spec.agent == "graph":
        cards.append(GRAPH_SCHEMA_CARD)
    if spec.agent == "vector" or "find_similar_cases" in spec.tools:
        cards.append(VECTOR_SCHEMA_CARD)
    if not cards:
        fallback = SCHEMA_BY_AGENT.get(spec.agent, "")
        if fallback:
            cards.append(fallback)
    schema_block = ("\n\n" + "\n\n".join(cards)) if cards else ""
    # Fixed demo anchor: the synthetic data is dated relative to this, so any 'recent'/
    # 'last N days'/'this month' window must be computed against it, not the real clock.
    today = f"\nToday's date is {settings.demo_reference_date}; compute recency windows from it."
    inventory = ""
    emitter = CURRENT_EMITTER.get()
    if emitter is not None:
        block = bus.context_inventory(emitter.run_id)
        if block:
            inventory = (
                f"\n\n{block}\nUse list_files / read_file / read_artifact to reopen any of these; "
                "reference them by id/title when composing a report or follow-up."
            )
    return f"{spec.prompt}{case}{memory}{schema_block}{today}{inventory}\nWrite the final specialist finding in {lang}."


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

    Streams the subgraph with stream_mode=["messages","updates"]:
    - "messages" chunks from the reason node feed a live thinking step (tokens visible
      as they generate).
    - "updates" captures the final finding and tool-call reasoning.
    """
    import time as _time

    emitter: RunEmitter | None = CURRENT_EMITTER.get()
    subgraph = build_specialist_subgraph(
        spec, language=language, case_context=case_context, memories=memories, extra_tools=extra_tools,
    )
    messages = [*_bounded_history(history), HumanMessage(content=subtask)]
    final = ""
    last_tool_text = ""  # fallback if the model never composes a final answer (budget/recursion cap)
    thinking_buf = ""
    thinking_step_id: str | None = None
    last_emit_t: float = 0.0
    THROTTLE_S = 0.12
    # Accumulated partial tool-call args keyed by tool_call index -- used to stream the
    # run_python `code` argument as the model writes it (typing effect in the UI).
    code_bufs: dict[int, str] = {}
    code_step_ids: dict[int, str] = {}
    last_code_emit_t: float = 0.0

    try:
      async for event in subgraph.astream(
        {"messages": messages},
        {"recursion_limit": recursion_limit},
        stream_mode=["messages", "updates"],
      ):
        # event is a tuple (stream_type, payload) when multiple stream modes
        if isinstance(event, tuple) and len(event) == 2:
            stream_type, payload = event
        else:
            stream_type, payload = "updates", event

        if stream_type == "messages":
            chunk, _metadata = payload if isinstance(payload, tuple) else (payload, {})
            if not isinstance(chunk, AIMessageChunk):
                continue

            # Stream partial tool-call arguments for run_python into code frames.
            for tc in getattr(chunk, "tool_call_chunks", None) or []:
                if not isinstance(tc, dict):
                    # LangChain may yield objects with .get-like attrs
                    name = getattr(tc, "name", None) or ""
                    args_delta = getattr(tc, "args", None) or ""
                    idx = getattr(tc, "index", 0) or 0
                else:
                    name = tc.get("name") or ""
                    args_delta = tc.get("args") or ""
                    idx = tc.get("index", 0) or 0
                if name and name != "run_python":
                    continue
                if not args_delta:
                    continue
                # Once we know the name is run_python (or name is empty mid-stream after
                # a prior run_python chunk for this index), accumulate.
                if name == "run_python" or idx in code_bufs:
                    code_bufs[idx] = code_bufs.get(idx, "") + str(args_delta)
                    # Best-effort extract of the "code" field from the growing JSON args.
                    snippet = _extract_code_arg(code_bufs[idx])
                    if snippet and emitter:
                        now = _time.monotonic()
                        if now - last_code_emit_t >= THROTTLE_S:
                            last_code_emit_t = now
                            step_id = code_step_ids.setdefault(
                                idx, f"code_{spec.key}_{idx}_{id(subgraph)}"
                            )
                            emitter.code(CodePayload(
                                step_id=step_id, phase="template",
                                language="python", code=snippet[-200000:],
                            ))

            reasoning, answer_text = _split_reasoning_and_answer(chunk.content)
            token_text = reasoning or answer_text
            if token_text and emitter and not getattr(chunk, "tool_calls", None):
                thinking_buf += token_text
                now = _time.monotonic()
                if now - last_emit_t >= THROTTLE_S:
                    last_emit_t = now
                    if thinking_step_id is None:
                        thinking_step_id = f"think_{spec.key}_{id(subgraph)}"
                    emitter._emit_step(
                        thinking_step_id, spec.agent, "thinking",
                        spec.friendly_action or f"{spec.display} thinking",
                        "running", specialist=spec.display,
                        detail=_strip_thinking_tags(thinking_buf[-800:]),
                    )

        elif stream_type == "updates":
            for _node, node_payload in (payload or {}).items():
                for message in (node_payload or {}).get("messages", []) or []:
                    if isinstance(message, ToolMessage):
                        # Keep the last substantive tool result so a specialist that hits
                        # its budget/recursion cap without composing a final answer still
                        # surfaces real findings instead of a generic "no answer".
                        tool_text = _text_of(message.content).strip()
                        if len(tool_text) > 80 and "STOP querying" not in tool_text:
                            last_tool_text = tool_text
                        continue
                    if not isinstance(message, AIMessage):
                        continue
                    text = _strip_thinking_tags(_text_of(message.content))
                    if getattr(message, "tool_calls", None):
                        # Close any "Writing Python" code frames once the tool call is final.
                        if emitter:
                            for idx, step_id in list(code_step_ids.items()):
                                snippet = _extract_code_arg(code_bufs.get(idx, ""))
                                emitter.code(CodePayload(
                                    step_id=step_id, phase="template",
                                    language="python", code=snippet[-200000:] or None,
                                ))
                                emitter._emit_step(
                                    step_id, spec.agent, "tool_call", "Writing Python",
                                    "done", specialist=spec.display, tool_name="run_python",
                                )
                            code_step_ids.clear()
                            code_bufs.clear()
                        if text and emitter and not thinking_step_id:
                            emitter.step_once(
                                spec.agent, "thinking", spec.friendly_action or f"{spec.display} thinking",
                                specialist=spec.display, detail=text[:600],
                            )
                    elif text:
                        final = text
    except GraphRecursionError:
        # The ReAct loop exhausted its step budget mid-flight. Its tool calls already ran
        # and emitted their artifacts (e.g. find_links_between_cases' shared-identifier
        # graph), and last_tool_text holds the real finding -- so DON'T let the exception
        # escape and get replaced by a generic "couldn't converge" upstream. Fall through
        # to the return below and surface what the tools actually found.
        logger.warning("specialist %s hit its step budget; salvaging last tool finding", spec.key)

    if thinking_step_id and emitter:
        emitter._emit_step(
            thinking_step_id, spec.agent, "thinking",
            spec.friendly_action or f"{spec.display} thinking",
            "done", specialist=spec.display,
            detail=_strip_thinking_tags(thinking_buf[-800:]),
        )

    return final or last_tool_text or f"{spec.display} found no answer for that subtask."


def _extract_code_arg(partial_json: str) -> str:
    """Best-effort pull of the `code` string from a growing tool-call args JSON fragment."""
    if not partial_json or '"code"' not in partial_json:
        return ""
    match = re.search(r'"code"\s*:\s*"(.*)', partial_json, flags=re.DOTALL)
    if not match:
        return ""
    raw = match.group(1)
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            out.append(raw[i : i + 2])
            i += 2
            continue
        if ch == '"':
            break
        out.append(ch)
        i += 1
    text = "".join(out)
    return text.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
