"""Entry point for building the assistant's runtime.

Default (`ASSISTANT_MULTI_AGENT=true`): `build_agent` compiles and returns the explicit
LangGraph **supervisor graph** (see graph.py) -- a real `StateGraph` with a planner node,
`Send` fan-out to specialist ReAct *subgraphs*, and a fan-in synthesizer, over a typed
state with a reducer.

Fallback (`ASSISTANT_MULTI_AGENT=false`): a single `create_react_agent` loop over the whole
toolbox. Kept as an instant, low-risk escape hatch for the live demo -- if the graph ever
misbehaves on stage, flip the flag and the assistant still answers.

The prompt below teaches capability, not answers; the scenario playbooks are examples of
how to chain tools, not a script.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from ..llm import build_llm_pair
from ..config import settings
from .tools import build_tools

logger = logging.getLogger(__name__)

# A genuinely free-form question (an off-script judge question, say) can need a wrong
# turn or two before the agent finds the right table/join -- 8 left no room to recover
# once the model's first instinct was wrong (confirmed live: a smaller model tried to
# join Transaction straight to CaseMaster, which has no such FK, retried variations of
# the same wrong join, and hit the ceiling with zero answer).
MAX_ITERATIONS = 10

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi (हिन्दी)", "kn": "Kannada (ಕನ್ನಡ)"}

SYSTEM_PROMPT = """You are the Crime Intelligence Assistant for the Karnataka State Police, helping an Investigating Officer (IO) work cyber and financial crime cases.

You answer from three stores, through tools only:
- SQL (Postgres): the record of facts — cases, people, charges, transactions, evidence.
- GRAPH (Neo4j): the links — who/what connects to whom, money movement, shared infrastructure.
- VECTOR (Pinecone): meaning — finding cases with the same modus operandi even when every name, number and account differs.

## Absolute rules

1. **Never invent a fact.** Every name, number, amount, date, account and citation you state must have come back from a tool in this conversation. If a tool returns nothing, say so plainly and suggest what would answer it. An honest "not found" is a correct answer; a plausible guess is a serious failure in police work.
2. **Decision support, not accusation.** Report links and patterns as investigative leads for the officer to verify. Never assert guilt. Say "shares a device with", not "is guilty of".
3. **Case data is synthetic; statutes and precedents are real.** Cite judgments exactly as the legal tools return them.
4. **Prefer the specific tool.** Use run_sql_select / run_cypher_read when nothing else fits — they are read-only and safe, and a real question the other tools miss is exactly what they are for. Never refuse a question just because it isn't one of the examples below.
5. If the officer's question is ambiguous but a reasonable default exists, take it and say what you assumed. Ask only when you genuinely cannot proceed.

## How to work

Think about which store answers the question, call the tool, read what came back, and chain if the answer opens a next hop. Common chains:
- meaning → structure: find_similar_cases, then find_links_between_cases on the refs it returns.
- identifier → network: expand_entity, then trace_money_flow or person_history.
- facts → law: get_case_summary, then legal_checklist.

Call several tools when a question has several parts. Stop as soon as you can answer.

## Example patterns (illustrations, NOT a script — real questions will differ)

- "Summarise this case and the timeline" → get_case_summary.
- "Where did the money go, and how fast?" → trace_money_flow. Lead with what is still freezable; that is the actionable part.
- "Has this MO appeared elsewhere?" → find_similar_cases, then offer find_links_between_cases.
- "Do we know this accused?" → person_history — aliases resolve through shared device/UPI/phone.
- "Is this surge organised?" → detect_community (crime_type + days), then query_case_stats for the trend.
- "Is this prosecutable? What's missing?" → legal_checklist. Amber means the evidence exists but is not admissible yet — usually a missing BSA §63 certificate.
- "Which districts are worst for X?" → query_case_stats, or run_sql_select for anything more specific.

## Writing the answer

Lead with the finding — the thing the officer would act on. Then the support. Be concrete: name the account, the amount, the district, the date. Use short paragraphs; use a list only for genuinely enumerable things. Do not describe your own process ("I called the graph tool") — the reasoning trail already shows it. Do not restate a whole table the officer can see in the artifact; pull out what matters.

State uncertainty where it exists: a 0.71 similarity is "possible", not "confirmed"."""


def _language_clause(language: str) -> str:
    name = LANGUAGE_NAMES.get(language, LANGUAGE_NAMES["en"])
    if language == "en":
        return "\n\n## Language\n\nWrite your answer in English."
    return f"""

## Language

Write your ENTIRE answer to the officer in {name}. This is mandatory — the officer has selected {name}.

Keep verbatim, never translated or transliterated: statute names and numbers (BNS 318, IT Act 66D, PMLA 3, BSA 63), case citations and court names, account numbers, UPI IDs, IMEIs, phone numbers, IP addresses, CrimeNos, and person names as recorded.
Translate the surrounding explanation, findings and recommendations into {name}. Amounts may use Indian units (lakh/crore) written in {name}."""


def _memory_clause(memories: list[str]) -> str:
    if not memories:
        return ""
    lines = "\n".join(f"- {m}" for m in memories)
    return (
        "\n\n## About this officer\n\n"
        "Remembered from earlier sessions — apply where relevant, but never let it override "
        f"what the tools return now:\n{lines}"
    )


def _case_clause(case_context: dict[str, Any] | None) -> str:
    if not case_context:
        return ""
    return (
        f"\n\n## Case in context\n\nThe officer is working case "
        f"{case_context.get('crime_no')} (case_id={case_context.get('case_id')}). "
        f"When they say \"this case\", they mean this one — tools accept an empty case_ref to use it."
    )


def build_system_prompt(
    language: str = "en",
    case_context: dict[str, Any] | None = None,
    memories: list[str] | None = None,
) -> str:
    return (
        SYSTEM_PROMPT
        + _case_clause(case_context)
        + _memory_clause(memories or [])
        + _language_clause(language)
    )


def build_history(turns: list[dict[str, Any]]) -> list[Any]:
    """Prior turns -> messages, so follow-ups ('and the third one?') resolve."""
    messages: list[Any] = []
    for turn in turns:
        role, content = turn.get("role"), turn.get("content") or ""
        if not content:
            continue
        messages.append(HumanMessage(content=content) if role == "user" else AIMessage(content=content))
    return messages


def build_agent(
    language: str = "en",
    case_context: dict[str, Any] | None = None,
    memories: list[str] | None = None,
    extra_tools: list[Any] | None = None,
    history: list[Any] | None = None,
):
    """Compile the runtime -- the supervisor graph by default, the ReAct loop as fallback.

    Both return a compiled LangGraph object with the same `astream`/`ainvoke` interface, so
    service.py drives either the same way. `history` is the prior turns of THIS session (as
    LangChain messages); it makes follow-ups stateful -- the graph bakes it into the planner
    and every specialist. with_fallbacks on the model keeps a demo alive when the primary
    provider rate-limits (see llm.py::_FALLBACK_PROVIDER).
    """
    if settings.assistant_multi_agent:
        # Lazy import breaks the agent<->graph module cycle (graph.py imports nothing from
        # here at module load; this import happens only when a run is built).
        from .graph import build_assistant_graph
        return build_assistant_graph(
            language=language, case_context=case_context, memories=memories,
            extra_tools=extra_tools, history=history,
        )

    primary, fallback = build_llm_pair(purpose="conv_ai")
    model = primary.with_fallbacks([fallback])
    tools = build_tools(extra=extra_tools)
    prompt = build_system_prompt(language, case_context, memories)
    logger.info(
        "assistant: single-loop agent built tools=%d language=%s case=%s memories=%d",
        len(tools), language, (case_context or {}).get("crime_no"), len(memories or []),
    )
    return create_react_agent(model, tools, prompt=SystemMessage(content=prompt))
