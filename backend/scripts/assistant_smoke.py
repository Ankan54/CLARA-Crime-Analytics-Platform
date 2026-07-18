"""assistant_smoke.py -- drive the real agent end to end.

Needs live Postgres + Neo4j + Pinecone + an LLM (whatever CHAT_LLM_PROVIDER points at).
No FastAPI server: it calls run_assistant directly and reads the event stream off the bus,
so a failure points at the agent rather than at transport.

    python backend/scripts/assistant_smoke.py                # everything
    python backend/scripts/assistant_smoke.py --only scenarios
    python backend/scripts/assistant_smoke.py --only offscript,kannada,pdf,cancel

The off-script cases matter as much as the scenarios: judges will type their own
questions, and an agent that only answers the four rehearsed ones is a puppet show. Those
prompts are deliberately NOT in any suggested-prompt list.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

# Kannada/Hindi answers are the whole point of two of these checks. Windows' console
# defaults to cp1252, which has no Devanagari/Kannada glyphs -- printing them raised
# UnicodeEncodeError and killed the rest of the suite mid-run (confirmed live: the
# process died right after the Kannada check *passed*, silently skipping pdf/cancel).
# errors="replace" degrades to visible '?' rather than crashing.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.assistant import bus, service  # noqa: E402

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}\n        {detail}")
    results.append((name, ok, detail))


def _summarise(run_id: str) -> dict:
    events = bus.history(run_id)
    steps = [e["step"] for e in events if e["type"] == "step"]
    return {
        "answer": "".join(e["delta"] for e in events if e["type"] == "answer_delta"),
        "steps": steps,
        "agents": {s["agent"] for s in steps},
        "tools": [s["title"] for s in steps if s["kind"] == "tool_call"],
        "artifacts": [e["artifact"] for e in events if e["type"] == "artifact"],
        "citations": [e["citation"] for e in events if e["type"] == "citation"],
        "actions": [e["action"] for e in events if e["type"] == "action"],
        "terminal": events[-1]["type"] if events else None,
        "errored": [e for e in events if e["type"] == "error"],
    }


_SESSION_ID = "smoke-session"
_session_ready = False


def _ensure_smoke_session() -> None:
    """The real HTTP flow always calls persistence.ensure_session() before
    run_assistant() (routers/assistant.py::post_message). Calling run_assistant directly,
    as this script does, skips that -- so AssistantArtifact's FK to AssistantSession
    (added in 003_assistant_tables.sql) fails the moment a tool tries to save an
    artifact. Do it once, here, so the smoke script matches the real call order."""
    global _session_ready
    if _session_ready:
        return
    from app.assistant import persistence

    persistence.ensure_session(_SESSION_ID, "smoke-user", "Assistant smoke test", None, "en")
    _session_ready = True


async def _ask(prompt: str, case_context=None, language="en", run_id=None, extra_tools=None) -> dict:
    _ensure_smoke_session()
    run_id = run_id or f"smoke-{int(time.time() * 1000)}"
    started = time.monotonic()
    await service.run_assistant(
        run_id=run_id, session_id=_SESSION_ID, prompt=prompt,
        case_context=case_context, language=language, extra_tools=extra_tools or [],
    )
    out = _summarise(run_id)
    out["seconds"] = round(time.monotonic() - started, 1)
    out["run_id"] = run_id
    return out


def _case(crime_no: str) -> dict | None:
    from sqlalchemy import text

    from app.db import db_session

    with db_session() as db:
        row = db.execute(text(
            "SELECT CaseMasterID AS case_id, CrimeNo AS crime_no FROM CaseMaster WHERE CrimeNo = :v"
        ), {"v": crime_no}).mappings().first()
    return dict(row) if row else None


# Scenario crime numbers come from frontend/src/data/scenarios.ts.
SCENARIOS = [
    ("digital-arrest", "129011001202690001", "Where did the money go, and how fast?", {"graph"}),
    ("many-names", "129011005202690002", "Do we already know this accused? Show his history.", {"graph"}),
    ("follow-money", "129191018202690003", "Trace this money as far as it goes.", {"graph"}),
    ("surge", "129011002202690004", "Is this part of a known pattern? Is the surge organised?", {"vector", "sql", "graph"}),
]

# Nothing scripted anticipates these. They exercise the guarded raw-query tools.
OFF_SCRIPT = [
    "Which districts have the most cyber crime cases? Give me the top five.",
    "How many cases were registered each month this year?",
    "Find any account that appears in more than one case, and tell me which cases.",
]


async def run_scenarios() -> None:
    print("\n== Scenario prompts ==")
    for key, crime_no, prompt, expect_agents in SCENARIOS:
        case = _case(crime_no)
        if not case:
            # Not a failure: some scenario cases are held back from the historical corpus
            # by design and only exist once the officer uploads that scenario's live FIR
            # (scenario 4's is one). Reloading will NOT create them.
            print(f"  SKIP  {key}: {crime_no} not in CaseMaster yet\n"
                  f"        This case arrives via the demo upload flow - ingest scenario "
                  f"'{key}' first, then re-run. (Reloading the corpus won't add it.)")
            continue
        out = await _ask(prompt, case_context=case)
        ok = (
            out["terminal"] == "done"
            and bool(out["answer"].strip())
            and bool(out["artifacts"])
            and bool(expect_agents & out["agents"])
        )
        record(
            f"{key}: {prompt[:44]}...", ok,
            f"{out['seconds']}s | agents={sorted(out['agents'])} | tools={out['tools']} | "
            f"artifacts={[a['kind'] for a in out['artifacts']]} | answer={len(out['answer'])} chars",
        )
        if out["answer"]:
            print(f"        > {out['answer'][:150].replace(chr(10), ' ')}...")


async def run_offscript() -> None:
    print("\n== Off-script questions (guarded raw-query tools) ==")
    for prompt in OFF_SCRIPT:
        out = await _ask(prompt)
        # No artifact requirement: a free-form answer may legitimately be prose. What
        # must hold is that it finished, used a specialist, and said something.
        ok = out["terminal"] == "done" and bool(out["answer"].strip()) and bool(out["agents"] - {"supervisor"})
        record(
            f"off-script: {prompt[:44]}...", ok,
            f"{out['seconds']}s | agents={sorted(out['agents'])} | tools={out['tools']} | "
            f"answer={len(out['answer'])} chars",
        )
        if out["answer"]:
            print(f"        > {out['answer'][:150].replace(chr(10), ' ')}...")


async def run_legal() -> None:
    print("\n== Legal checklist (needs EXT_SectionMap + EXT_ElementSatisfiedBy) ==")
    case = _case("129011001202690001")
    if not case:
        record("legal: case present", False, "scenario 1 case missing")
        return
    out = await _ask("Is this prosecutable? What am I missing?", case_context=case)
    ok = out["terminal"] == "done" and "legal" in out["agents"] and bool(out["artifacts"])
    record(
        "legal: is this prosecutable?", ok,
        f"{out['seconds']}s | agents={sorted(out['agents'])} | citations={len(out['citations'])} | "
        f"artifacts={[a['kind'] for a in out['artifacts']]}",
    )
    for citation in out["citations"][:3]:
        print(f"        cited: {citation.get('label')}")


async def run_kannada() -> None:
    print("\n== Kannada (hackathon requirement) ==")
    case = _case("129011001202690001")
    out = await _ask("Summarise this case.", case_context=case, language="kn")
    answer = out["answer"]
    has_kannada = any("ಀ" <= ch <= "೿" for ch in answer)
    record(
        "kannada: answer is in Kannada", out["terminal"] == "done" and has_kannada,
        f"{out['seconds']}s | kannada_script={has_kannada} | answer={len(answer)} chars",
    )
    if answer:
        print(f"        > {answer[:120]}")


async def run_pdf() -> None:
    print("\n== PDF report (hackathon requirement) ==")
    from app.assistant.skills.report import build_report_tool

    case = _case("129191018202690003")  # follow-money: richest money-trail data
    run_id = f"smoke-pdf-{int(time.time() * 1000)}"
    tool = build_report_tool(_SESSION_ID, run_id, "en", "PSI Smoke Test",
                             case_ref=(case or {}).get("crime_no", ""))
    out = await _ask(
        "Trace the money for this case, then generate a PDF report of what you found.",
        case_context=case, run_id=run_id, extra_tools=[tool],
    )
    pdfs = [a for a in out["artifacts"] if a.get("kind") == "document" and a.get("format") == "pdf"]
    record(
        "pdf: report generated and downloadable", bool(pdfs),
        f"{out['seconds']}s | artifacts={[a['kind'] for a in out['artifacts']]} | "
        f"pdf_url={(pdfs[0].get('url') if pdfs else None)}",
    )


async def run_cancel() -> None:
    print("\n== Cancel ==")
    _ensure_smoke_session()
    case = _case("129191018202690003")
    run_id = f"smoke-cancel-{int(time.time() * 1000)}"
    service.start_run(
        run_id=run_id, session_id=_SESSION_ID,
        prompt="Trace this money as far as it goes and check every mule account for links to other cases.",
        case_context=case,
    )
    # Let it get into the work, then stop it the way the Stop button does.
    await asyncio.sleep(6)
    cancelled = service.cancel_run(run_id)
    # Cancellation only lands between tool calls (a thread can't be interrupted
    # mid-query), so if the in-flight call is a slow one the terminal frame can trail
    # the cancel request by more than a fixed instant -- poll instead of a single sleep
    # (confirmed live: normally ~0.5s, but a single 1.5s sleep flaked under DB load).
    events: list = []
    for _ in range(20):
        await asyncio.sleep(0.5)
        events = bus.history(run_id)
        if events and events[-1]["type"] in ("done", "error"):
            break
    terminal = events[-1]["type"] if events else None
    # The UI has no onclose handler: a stop that doesn't emit `done` hangs the screen.
    record(
        "cancel: run stops and still terminates cleanly",
        cancelled and terminal == "done",
        f"cancel_accepted={cancelled} | terminal={terminal} | events={len(events)}",
    )


async def run_shape() -> None:
    """Drive the compiled supervisor graph once and assert the graph actually ran.

    Run this first. It confirms, against the live model, that:
      1. the planner (supervisor node) picks specialist(s),
      2. the specialist subgraph(s) run, and
      3. the synthesize (fan-in) node produces a `final_answer`.
    If the planner or a subgraph is misconfigured, every scenario returns an empty answer
    IDENTICALLY and falls through to the "I could not produce an answer" fallback -- which
    looks like a broken agent rather than a broken graph. Confirming the shape once here
    turns a confusing live session into a five-second answer.
    """
    print("\n== Graph shape (run this first) ==")
    from app.config import settings
    from app.assistant.agent import build_agent

    agent = build_agent(language="en", case_context=None, memories=[])
    if not settings.assistant_multi_agent:
        record("shape: multi-agent graph enabled", False,
               "ASSISTANT_MULTI_AGENT is off -- running the single-loop fallback, not the graph.")
        return

    updates: list[dict] = []
    async for update in agent.astream(
        {"question": "How many cyber crime cases are in the database?", "history": []},
        config={"recursion_limit": 25}, stream_mode="updates",
    ):
        updates.append(update)
        for node, payload in (update or {}).items():
            keys = list(payload) if isinstance(payload, dict) else type(payload).__name__
            print(f"    node={node:<12} update_keys={keys}")

    nodes = {n for u in updates for n in (u or {})}
    record("shape: supervisor -> specialists -> synthesize ran",
           "supervisor" in nodes and "synthesize" in nodes,
           f"nodes visited={sorted(nodes)}")

    finals = [
        u["synthesize"].get("final_answer")
        for u in updates
        if isinstance(u.get("synthesize"), dict) and u["synthesize"].get("final_answer")
    ]
    record("shape: synthesize produced a final answer", bool(finals),
           f"final_answer chars={len(finals[-1]) if finals else 0}")


SUITES = {
    "shape": run_shape,
    "scenarios": run_scenarios,
    "offscript": run_offscript,
    "legal": run_legal,
    "kannada": run_kannada,
    "pdf": run_pdf,
    "cancel": run_cancel,
}


async def main_async(only: list[str]) -> int:
    from app.config import settings

    print(f"provider={settings.chat_llm_provider} model={settings.chat_llm_id or '(provider default)'}")
    for name in only:
        await SUITES[name]()

    print("\n--- Summary ---")
    failed = [r for r in results if not r[1]]
    for name, ok, _ in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{len(results) - len(failed)}/{len(results)} passed.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=",".join(SUITES),
                        help=f"comma-separated: {', '.join(SUITES)}")
    args = parser.parse_args()
    only = [s.strip() for s in args.only.split(",") if s.strip()]
    unknown = [s for s in only if s not in SUITES]
    if unknown:
        print(f"Unknown suite(s): {unknown}. Choose from {list(SUITES)}")
        return 2
    return asyncio.run(main_async(only))


if __name__ == "__main__":
    sys.exit(main())
