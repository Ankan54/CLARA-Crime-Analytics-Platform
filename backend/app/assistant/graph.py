"""The multi-agent supervisor -- an explicit LangGraph `StateGraph`.

Shape (parent graph):

        START
          |
     [ supervisor ]                LLM planner: decides WHICH specialists + writes a
          |  (conditional edge                 self-contained subtask for each
          |   returns a list of Send)
          v
    fan-out via Send  ------> [ case ] [ financial ] [ network ] [ mo ] [ legal ]
    (parallel superstep)          \        \        |       /        /
                                   \        \       |      /        /   each node runs
                                    v        v      v     v        v    that specialist's
                                        [ synthesize ]              <-- COMPILED SUBGRAPH
                                              |    fan-in: reads the reduced
                                              v    specialist_results list
                                             END

Why this is a graph and not a ReAct loop:

  * State: one typed `AssistantState` (graph_state.py) flows through every node, with an
    `operator.add` reducer on `specialist_results` so parallel branches merge instead of
    clobbering (fan-in).
  * Supervisor: the `supervisor` node is an LLM planner. Its conditional edge returns a
    list of `Send` objects -- LangGraph's dynamic fan-out primitive -- so the chosen
    specialists run in ONE parallel superstep (map). `synthesize` is the reduce.
  * Subgraphs: each specialist node wraps a compiled ReAct *subgraph* (specialists.py),
    translating this graph's `AssistantState` to the subgraph's `MessagesState` and back.

Streaming to the UI is decoupled from the graph run: nodes and tools publish steps through
the `RunEmitter` (carried on a ContextVar), so the graph itself just runs to a final state
while the officer watches the trail fill live. That mirrors how the reference system
decouples its Redis event bus from the graph invocation.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from ..llm import build_llm_pair
from .emitter import RunEmitter
from .events import PlanPayload, PlanTask
from .graph_state import AssistantState, SpecialistResult
from .skills.playbooks import build_playbook_tools
from .specialists import SPEC_BY_KEY, SPECS, run_specialist
from .tools import CURRENT_EMITTER, CURRENT_SPECIALIST

logger = logging.getLogger(__name__)

# The specialist ReAct subgraphs get their own recursion budget. LangGraph counts every
# node visit, so an N-iteration cap is ~2N+1 supersteps (reason + tools per iteration).
MAX_SPECIALIST_ITERATIONS = 10
SPECIALIST_RECURSION_LIMIT = 2 * MAX_SPECIALIST_ITERATIONS + 1

_LANG_NAME = {"en": "English", "hi": "Hindi", "kn": "Kannada"}

_SPECIALIST_KEYS = tuple(spec.key for spec in SPECS)


# --- planner structured output ----------------------------------------------


class _Assignment(BaseModel):
    specialist: Literal["case", "financial", "network", "mo", "legal"] = Field(
        description="Which specialist should handle this part of the question."
    )
    subtask: str = Field(
        description=(
            "A self-contained instruction for this specialist. Spell out the case reference "
            "and any identifiers it needs -- it does NOT see the officer's original wording."
        )
    )


class _RoutingPlan(BaseModel):
    assignments: list[_Assignment] = Field(
        description="Smallest set of specialists that fully answers the question. One for a "
        "simple question; several (run in parallel) for a composite one."
    )


_PLANNER_INSTRUCTIONS = """You are the supervisor of a Karnataka State Police crime-intelligence team. Route the Investigating Officer's question to the specialist(s) who can answer it.

Specialists:
- case: {case}
- financial: {financial}
- network: {network}
- mo: {mo}
- legal: {legal}

Rules:
- Pick the SMALLEST set that fully answers the question.
- A simple, single-topic question -> exactly ONE specialist.
- A composite question ("summarise the case AND trace the money", "is this a ring AND where") -> the few specialists it needs; they run in parallel.
- For each specialist, write a self-contained `subtask` that includes the case reference and any identifiers, so the specialist needs nothing but that string.
- This is a CONVERSATION. If the latest question is a follow-up ("what about the third one?", "trace that account", "now show it as a chart", "explain in Kannada"), resolve the reference from the messages above and write the subtask in FULL, naming the actual case / account / entity being referred to. Never pass a dangling pronoun to a specialist.
- Never pick a specialist that adds nothing.{case_line}"""


def _heuristic_plan(question: str, case_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Keyword routing -- the safety net if the planner LLM errors or returns nothing.

    A demo must never die at the routing step, so a wrong-but-plausible route beats a crash.
    """
    q = (question or "").lower()
    picks: list[str] = []
    if any(w in q for w in ("money", "fund", "trace", "freez", "transfer", "upi", "account", "launder", "crypto", "mule")):
        picks.append("financial")
    if any(w in q for w in ("similar", "same script", "modus", " mo ", "pattern", "trend", "surge", "hotspot", "spike")):
        picks.append("mo")
    if any(w in q for w in ("link", "ring", "gang", "alias", "same person", "repeat", "network", "shared", "community", "cluster", "history")):
        picks.append("network")
    if any(w in q for w in ("charge", "section", "prosecut", "admissib", "precedent", "legal", "evidence", "bsa", "pmla", "bns", "convict", "acquit")):
        picks.append("legal")
    if any(w in q for w in ("summar", "timeline", "about", "brief", "parties", "what is this case", "overview")):
        picks.append("case")
    if not picks:
        picks = ["case"] if case_context else ["mo"]
    # Preserve order but de-dup.
    seen: set[str] = set()
    ordered = [p for p in picks if not (p in seen or seen.add(p))]
    return [
        {"key": k, "display": SPEC_BY_KEY[k].display, "agent": SPEC_BY_KEY[k].agent, "subtask": question}
        for k in ordered
    ]


def _text_of(content: Any) -> str:
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


def _looks_like_provider_block(text: str) -> bool:
    low = (text or "").lower()
    return "content filter" in low or "generated text has been blocked" in low


def _word_chunks(text: str, per_chunk: int = 6) -> list[str]:
    if not text:
        return []
    words = text.split(" ")
    return [
        " ".join(words[i:i + per_chunk]) + (" " if i + per_chunk < len(words) else "")
        for i in range(0, len(words), per_chunk)
    ]


def build_assistant_graph(
    *,
    language: str = "en",
    case_context: dict[str, Any] | None = None,
    memories: list[str] | None = None,
    extra_tools: list[Any] | None = None,
    history: list[Any] | None = None,
):
    """Compile the supervisor `StateGraph` for one run.

    Everything the nodes need (language, the case in context, per-agent extra tools, and
    this session's prior turns) is captured in these closures at build time, so the flowing
    state stays minimal -- just the question, the plan, and the specialist results.

    `history` is what makes a turn stateful: the same session's prior messages are baked in
    here, read by the planner (to resolve "that account" / "the third one" / "now in
    Kannada") and passed to every specialist (so its ReAct loop has the conversation too).
    It is loaded fresh from Postgres each turn by the router, so it survives restarts and is
    never a stale in-memory copy.
    """
    lang_name = _LANG_NAME.get(language, "English")
    _history = list(history or [])
    primary, fallback = build_llm_pair(purpose="conv_ai")
    planner = primary.with_structured_output(_RoutingPlan).with_fallbacks(
        [fallback.with_structured_output(_RoutingPlan)]
    )
    composer = primary.with_fallbacks([fallback])
    # extra_tools are supervisor-wide report/code/memory tools; every specialist gets them.
    _extra = list(extra_tools or [])
    # Skills are agent-specific: each specialist only sees the playbooks it can execute
    # (the SKILL.md `agents` frontmatter), so a description-triggered skill can't misfire
    # into an agent that lacks the tools to run it.
    _playbooks = {spec.key: build_playbook_tools(spec.key) for spec in SPECS}

    case_line = ""
    if case_context:
        case_line = (
            f"\n\nThe officer is working case {case_context.get('crime_no')} "
            f"(case_id={case_context.get('case_id')}). \"this case\" means that one; an empty "
            f"case_ref uses it."
        )
    planner_system = _PLANNER_INSTRUCTIONS.format(
        case={s.key: s.description for s in SPECS}["case"],
        financial={s.key: s.description for s in SPECS}["financial"],
        network={s.key: s.description for s in SPECS}["network"],
        mo={s.key: s.description for s in SPECS}["mo"],
        legal={s.key: s.description for s in SPECS}["legal"],
        case_line=case_line,
    )

    async def supervisor(state: AssistantState) -> dict[str, Any]:
        question = state.get("question") or ""
        emitter: RunEmitter | None = CURRENT_EMITTER.get()

        async def _plan() -> list[dict[str, Any]]:
            messages = [{"role": "system", "content": planner_system}]
            for msg in _history[-6:]:
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                messages.append({"role": role, "content": _text_of(getattr(msg, "content", "")) or ""})
            messages.append({"role": "user", "content": question})
            try:
                result: _RoutingPlan = await planner.ainvoke(messages)
            except Exception:
                logger.exception("assistant: planner failed, using heuristic routing")
                return _heuristic_plan(question, case_context)
            plan: list[dict[str, Any]] = []
            seen: set[str] = set()
            for a in result.assignments:
                if a.specialist in SPEC_BY_KEY and a.specialist not in seen:
                    seen.add(a.specialist)
                    spec = SPEC_BY_KEY[a.specialist]
                    plan.append({
                        "key": spec.key, "display": spec.display, "agent": spec.agent,
                        "subtask": a.subtask.strip() or question,
                    })
            return plan or _heuristic_plan(question, case_context)

        if emitter:
            detail = (f"Case {case_context.get('crime_no')} in context."
                      if case_context else "No case in context - answering across the corpus.")
            with emitter.step("supervisor", "route", "Routing to specialists",
                              tool_name="route", detail=detail) as handle:
                plan = await _plan()
                handle.output = "Selected: " + ", ".join(t["display"] for t in plan)
        else:
            plan = await _plan()

        if emitter:
            emitter.plan(PlanPayload(tasks=[
                PlanTask(id=t["key"], title=t["display"], specialist=t["display"], status="running")
                for t in plan
            ]))
        logger.info("assistant: plan=%s", [t["key"] for t in plan])
        return {"plan": plan}

    def route_to_specialists(state: AssistantState) -> list[Send]:
        plan = state.get("plan") or []
        if not plan:
            plan = _heuristic_plan(state.get("question") or "", case_context)
        return [
            Send(t["key"], {"specialist_key": t["key"], "subtask": t["subtask"]})
            for t in plan
        ]

    async def _run_specialist_node(state: AssistantState, *, key: str) -> dict[str, Any]:
        spec = SPEC_BY_KEY[key]
        subtask = state.get("subtask") or state.get("question") or ""
        specialist_extras = _extra + _playbooks.get(key, [])
        emitter: RunEmitter | None = CURRENT_EMITTER.get()
        # Label every step this branch emits (including inner tool steps) with the
        # specialist. A ContextVar set inside this coroutine is isolated to this parallel
        # branch's task, so concurrent specialists never cross-label each other.
        token = CURRENT_SPECIALIST.set(spec.display)
        try:
            if emitter:
                with emitter.step(
                    spec.agent, "tool_call", f"{spec.display} working",  # type: ignore[arg-type]
                    specialist=spec.display, tool_name=f"ask_{spec.key}_agent",
                    tool_input={"subtask": subtask},
                ) as handle:
                    text = await run_specialist(
                        spec, subtask, language=language, case_context=case_context,
                        memories=memories, extra_tools=specialist_extras, history=_history,
                        recursion_limit=SPECIALIST_RECURSION_LIMIT,
                    )
                    handle.output = text[:600]
            else:
                text = await run_specialist(
                    spec, subtask, language=language, case_context=case_context,
                    memories=memories, extra_tools=specialist_extras, history=_history,
                    recursion_limit=SPECIALIST_RECURSION_LIMIT,
                )
        finally:
            CURRENT_SPECIALIST.reset(token)
        result: SpecialistResult = {
            "key": spec.key, "display": spec.display, "agent": spec.agent,
            "subtask": subtask, "text": text,
        }
        return {"specialist_results": [result]}

    async def synthesize(state: AssistantState) -> dict[str, Any]:
        results = state.get("specialist_results") or []
        question = state.get("question") or ""
        emitter: RunEmitter | None = CURRENT_EMITTER.get()

        if not results:
            answer = ("I could not produce an answer for that. Try naming the case by its "
                      "CrimeNo, or ask for something more specific.")
        elif len(results) == 1:
            # One specialist already wrote a finding-first answer in the target language;
            # a second compose pass would only add latency and provider-block risk.
            answer = results[0]["text"].strip()
        else:
            answer = await _compose(results, question)

        for piece in _word_chunks(answer):
            if emitter:
                emitter.answer_delta(piece)
            await asyncio.sleep(0)  # let frames leave the socket as produced
        return {"final_answer": answer}

    async def _compose(results: list[SpecialistResult], question: str) -> str:
        findings = "\n\n".join(f"[{r['display']}]\n{r['text']}" for r in results)
        convo = ""
        if _history:
            recent = "\n".join(
                f"{'Officer' if isinstance(m, HumanMessage) else 'Assistant'}: "
                f"{_text_of(getattr(m, 'content', ''))[:400]}"
                for m in _history[-4:] if _text_of(getattr(m, "content", ""))
            )
            if recent:
                convo = f"\n\nConversation so far (for continuity -- the question may be a follow-up):\n{recent}"
        prompt = (
            f"Combine these specialist findings into ONE grounded answer for the Investigating "
            f"Officer, written entirely in {lang_name}. Lead with the single most actionable "
            f"finding, then the support. Keep every identifier, amount, date and legal citation "
            f"exactly as given. Invent nothing beyond the findings. Do not mention specialists "
            f"or that a team was involved.{convo}\n\nOfficer's question: {question}\n\nFindings:\n{findings}"
        )
        try:
            message = await composer.ainvoke([HumanMessage(content=prompt)])
            text = _text_of(getattr(message, "content", "")).strip()
        except Exception:
            logger.exception("assistant: compose failed, concatenating findings")
            text = ""
        if not text or _looks_like_provider_block(text):
            # Fall back to the raw specialist findings rather than losing the answer.
            return "\n\n".join(f"{r['display']}: {r['text']}" for r in results)
        return text

    graph = StateGraph(AssistantState)
    graph.add_node("supervisor", supervisor)
    for spec in SPECS:
        graph.add_node(spec.key, functools.partial(_run_specialist_node, key=spec.key))
    graph.add_node("synthesize", synthesize)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_to_specialists, list(_SPECIALIST_KEYS))
    for spec in SPECS:
        graph.add_edge(spec.key, "synthesize")
    graph.add_edge("synthesize", END)

    compiled = graph.compile(name="assistant_supervisor")
    logger.info(
        "assistant: supervisor graph compiled specialists=%d language=%s case=%s extra_tools=%d",
        len(SPECS), language, (case_context or {}).get("crime_no"), len(_extra),
    )
    return compiled
