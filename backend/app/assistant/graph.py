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
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from ..llm import build_llm_pair
from .emitter import RunEmitter
from .events import PlanPayload, PlanTask
from .graph_state import AssistantState, SpecialistResult
from .persona import CLARA_CAPABILITIES, CLARA_IDENTITY, IN_SCOPE, NO_INTERNALS, OUT_OF_SCOPE
from .skills.playbooks import build_playbook_tools
from .specialists import SPEC_BY_KEY, SPECS, run_specialist
from .tools import CURRENT_EMITTER, CURRENT_SPECIALIST, RAW_QUERY_COUNT
from . import bus

logger = logging.getLogger(__name__)

# The specialist ReAct subgraphs get their own recursion budget. LangGraph counts every
# node visit, so an N-iteration cap is ~2N+1 supersteps (reason + tools per iteration).
# Set generously: the conv LLM tends to over-explore (run person_history AND several
# confirming queries) before it writes the finding, so a tight cap cut it off mid-analysis
# with no answer. 16 leaves room to explore and still compose; a true runaway is caught by
# the GraphRecursionError handler in _run_specialist_node (degrades to a partial finding).
MAX_SPECIALIST_ITERATIONS = 16
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
    mode: Literal["answer", "identity", "refuse"] = Field(
        default="answer",
        description="'answer' = route to specialists; 'identity' = CLARA self-description; 'refuse' = off-topic refusal.",
    )
    direct_answer: str | None = Field(
        default=None,
        description="For identity/refuse: the full response in the officer's language. Empty for answer mode.",
    )
    assignments: list[_Assignment] = Field(
        default_factory=list,
        description="Smallest set of specialists that fully answers the question. One for a "
        "simple question; several (run in parallel) for a composite one. Empty for identity/refuse.",
    )


_PLANNER_INSTRUCTIONS = """You are CLARA, the AI crime Analytics Assistant for a Karnataka State Police crime-intelligence team. Route the Investigating Officer's question to the specialist(s) who can answer it, OR handle it directly.

{clara_identity}

{clara_capabilities}

## Mode selection

Decide the mode FIRST:
- "identity": greetings, "who are you?", "what can you do?", "help" -> write `direct_answer` introducing yourself and your capabilities in {lang_name}. {no_internals}
- "refuse": the question is about {out_of_scope} or anything unrelated to crime investigation -> write a polite `direct_answer` in {lang_name} declining and stating what you CAN help with.
- "answer": the question is about {in_scope} -> fill `assignments` to route to specialists.
- A request to VISUALISE, chart, graph, plot, map, build a dashboard/interactive dashboard, or generate a report of in-scope crime data is ALWAYS "answer" mode. CLARA presents its analysis as interactive dashboards, charts and PDF reports — a specialist builds them. NEVER "refuse" a dashboard/chart/visualisation/report request and NEVER reply that you "are not a dashboard/visualisation tool"; you produce these.

## Specialists (only used in "answer" mode)
- case: {case}
- financial: {financial}
- network: {network}
- mo: {mo}
- legal: {legal}

Rules:
- Pick the SMALLEST set that fully answers the question.
- A simple, single-topic question -> exactly ONE specialist.
- "similar cases / same MO / same script / has this happened elsewhere / cases like this" -> `mo` ONLY. This answer stops at narrative similarity (which cases, what MO they share). Do NOT also assign `network`: checking whether those cases share an account/device/UPI is a SEPARATE follow-up the officer triggers next with "find links". Assigning `network` here spoils that next step.
- "find links / are these connected / do they share an account-device-UPI / same person / ring / gang / aliases" -> `network` (finding shared identifiers IS the link step). Only add `mo` if the officer also explicitly asked for MO/similarity in the SAME question.
- "dashboard / interactive dashboard / chart / graph / plot / visualise these stats / crime situation by district" -> `mo` (crime statistics & trends). It gathers the stats and builds the dashboard/chart itself. Use `case` instead when the visual is about one specific case; add `financial`/`network` too only if the dashboard must combine a money-trail or link view.
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
    if any(w in q for w in ("similar", "same script", "modus", " mo ", "pattern", "trend", "surge", "hotspot", "spike",
                            "dashboard", "chart", "graph", "plot", "visuali", "hotspots", "by district", "statistics", "stats")):
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
        clara_identity=CLARA_IDENTITY,
        clara_capabilities=CLARA_CAPABILITIES,
        no_internals=NO_INTERNALS,
        in_scope=IN_SCOPE,
        out_of_scope=OUT_OF_SCOPE,
        lang_name=lang_name,
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

        async def _route() -> tuple[str, str | None, list[dict[str, Any]]]:
            """Returns (mode, direct_answer, plan)."""
            messages = [{"role": "system", "content": planner_system}]
            for msg in _history[-6:]:
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                messages.append({"role": role, "content": _text_of(getattr(msg, "content", "")) or ""})
            messages.append({"role": "user", "content": question})
            try:
                result: _RoutingPlan = await planner.ainvoke(messages)
            except Exception:
                logger.exception("assistant: planner failed, using heuristic routing")
                return "answer", None, _heuristic_plan(question, case_context)

            mode = result.mode or "answer"
            if mode in ("identity", "refuse"):
                return mode, result.direct_answer or "", []

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
            return "answer", None, plan or _heuristic_plan(question, case_context)

        if emitter:
            detail = (f"Case {case_context.get('crime_no')} in context."
                      if case_context else "No case in context - answering across the corpus.")
            with emitter.step("supervisor", "route", "Understanding your question",
                              tool_name="route", detail=detail) as handle:
                mode, direct_answer, plan = await _route()
                if mode == "answer":
                    handle.output = "Deciding what to check: " + ", ".join(t["display"] for t in plan)
                else:
                    handle.output = f"Responding directly ({mode})"
        else:
            mode, direct_answer, plan = await _route()

        if mode == "answer" and emitter:
            emitter.plan(PlanPayload(tasks=[
                PlanTask(id=t["key"], title=SPEC_BY_KEY[t["key"]].friendly_action or t["display"],
                         specialist=t["display"], status="running")
                for t in plan
            ]))
        logger.info("assistant: mode=%s plan=%s", mode, [t["key"] for t in plan])
        return {"plan": plan, "direct_answer": direct_answer}

    def route_to_specialists(state: AssistantState) -> list[Send]:
        if state.get("direct_answer") is not None:
            # Send's payload REPLACES the node's input state (it does not merge with the
            # parent), so direct_answer must be threaded through explicitly or respond
            # sees an empty state and streams nothing.
            return [Send("respond", {"direct_answer": state.get("direct_answer")})]
        plan = state.get("plan") or []
        if not plan:
            plan = _heuristic_plan(state.get("question") or "", case_context)
        return [
            Send(t["key"], {"specialist_key": t["key"], "subtask": t["subtask"]})
            for t in plan
        ]

    async def respond(state: AssistantState) -> dict[str, Any]:
        """Direct response for identity/refuse -- no specialists needed."""
        answer = state.get("direct_answer") or ""
        emitter: RunEmitter | None = CURRENT_EMITTER.get()
        for piece in _word_chunks(answer):
            if emitter:
                emitter.answer_delta(piece)
            await asyncio.sleep(0)
        return {"final_answer": answer}

    async def _run_specialist_node(state: AssistantState, *, key: str) -> dict[str, Any]:
        spec = SPEC_BY_KEY[key]
        subtask = state.get("subtask") or state.get("question") or ""
        specialist_extras = _extra + _playbooks.get(key, [])
        emitter: RunEmitter | None = CURRENT_EMITTER.get()
        # Label every step this branch emits (including inner tool steps) with the
        # specialist. A ContextVar set inside this coroutine is isolated to this parallel
        # branch's task, so concurrent specialists never cross-label each other.
        token = CURRENT_SPECIALIST.set(spec.display)
        # Fresh raw-query budget per branch (ContextVar copies into each parallel Send task
        # and into tool worker threads), so the soft cap is per-specialist, not global.
        RAW_QUERY_COUNT.set([0])
        text = ""
        try:
            if emitter:
                with emitter.step(
                    spec.agent, "tool_call", spec.friendly_action or f"{spec.display} working",  # type: ignore[arg-type]
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
        except GraphRecursionError:
            # One branch exhausting its step budget must NOT crash the whole run -- the other
            # specialists' findings and a partial answer are far better than a dead turn.
            logger.warning("assistant: specialist %s hit its step budget; returning partial", spec.key)
            text = text or (
                "I investigated this in depth but could not fully converge within the analysis "
                "budget for this run. The steps I ran are in the reasoning trail; narrowing the "
                "question (e.g. naming the specific case or identifier) would let me finish."
            )
        except Exception:
            logger.exception("assistant: specialist %s failed", spec.key)
            text = text or "I could not complete this part of the analysis. Please try rephrasing the question."
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
            if emitter:
                emitter.answer_delta(answer)
        elif len(results) == 1:
            # The finding is already in hand -- stream it straight out (no extra LLM hop).
            answer = results[0]["text"].strip()
            for piece in _word_chunks(answer):
                if emitter:
                    emitter.answer_delta(piece)
                await asyncio.sleep(0)
        else:
            # P5: composing several findings into one answer needs another LLM call, which
            # is the gap the officer sees as a blank "Thinking…". Surface an explicit
            # composing state so there's visible movement until the first token lands.
            if emitter:
                emitter.step_once("supervisor", "thinking", "Composing the answer",
                                  detail="Combining the specialist findings into one reply\u2026")
            # _compose handles streaming internally via composer.astream
            answer = await _compose(results, question)

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
        inventory = ""
        if emitter_for_inventory := CURRENT_EMITTER.get():
            block = bus.context_inventory(emitter_for_inventory.run_id)
            if block:
                inventory = f"\n\n{block}"
        prompt = (
            f"You are CLARA. {NO_INTERNALS} "
            f"Combine these specialist findings into ONE grounded answer for the Investigating "
            f"Officer, written entirely in {lang_name}. Lead with the single most actionable "
            f"finding, then the support. Keep every identifier, amount, date and legal citation "
            f"exactly as given. Invent nothing beyond the findings. Do not mention specialists, "
            f"tools, or that a team was involved.{convo}{inventory}\n\n"
            f"Officer's question: {question}\n\nFindings:\n{findings}"
        )
        emitter: RunEmitter | None = CURRENT_EMITTER.get()
        try:
            full_text = ""
            buf = ""
            async for chunk in composer.astream([HumanMessage(content=prompt)]):
                token = _text_of(getattr(chunk, "content", ""))
                if not token:
                    continue
                full_text += token
                buf += token
                # Flush in small chunks so the answer visibly builds up. Emit from the very
                # first chunk -- an earlier `len(full_text) > 40` gate silently dropped the
                # answer's opening ~30 chars from the live stream (they only reappeared on
                # history reload), which read as the answer "popping in" mid-sentence.
                if len(buf) >= 24:
                    if emitter:
                        emitter.answer_delta(buf)
                    buf = ""
            if buf and emitter:
                emitter.answer_delta(buf)
            text = full_text.strip()
        except Exception:
            logger.exception("assistant: compose streaming failed, trying ainvoke fallback")
            try:
                message = await composer.ainvoke([HumanMessage(content=prompt)])
                text = _text_of(getattr(message, "content", "")).strip()
                if emitter and text:
                    for piece in _word_chunks(text):
                        emitter.answer_delta(piece)
            except Exception:
                logger.exception("assistant: compose ainvoke also failed")
                text = ""
        if not text or _looks_like_provider_block(text):
            fallback = "\n\n".join(f"{r['display']}: {r['text']}" for r in results)
            if emitter:
                for piece in _word_chunks(fallback):
                    emitter.answer_delta(piece)
            return fallback
        return text

    graph = StateGraph(AssistantState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("respond", respond)
    for spec in SPECS:
        graph.add_node(spec.key, functools.partial(_run_specialist_node, key=spec.key))
    graph.add_node("synthesize", synthesize)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_to_specialists, [*list(_SPECIALIST_KEYS), "respond"])
    for spec in SPECS:
        graph.add_edge(spec.key, "synthesize")
    graph.add_edge("respond", END)
    graph.add_edge("synthesize", END)

    compiled = graph.compile(name="assistant_supervisor")
    logger.info(
        "assistant: supervisor graph compiled specialists=%d language=%s case=%s extra_tools=%d",
        len(SPECS), language, (case_context or {}).get("crime_no"), len(_extra),
    )
    return compiled
