"""The assistant's toolbox.

Two families, on purpose:

  * Parameterised tools carry the marquee capabilities (money trail, link analysis,
    MO match, legal checklist). Their SQL/Cypher is written here, so the headline
    findings are deterministic and reviewable.
  * run_sql_select / run_cypher_read are guarded escape hatches. Judges will ask things
    nobody scripted ("which districts have the most cyber cases?"), and an agent that
    can only answer four questions is a demo, not a product.

Every tool body is synchronous and runs through _in_thread(). The Postgres, Neo4j and
Pinecone clients are all blocking; calling them straight from an async tool would stall
the event loop and, with it, every answer_delta token already streaming to the browser.

Emitters reach tools through a ContextVar rather than an argument, because LangGraph
constructs the tool call, not us. asyncio.to_thread copies the current context into the
worker thread, so CURRENT_EMITTER is still set inside the blocking body.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator

from langchain_core.tools import StructuredTool
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import SessionLocal
from . import stores
from .emitter import RunEmitter, StepHandle
from .events import (
    AssistantAction,
    AssistantCitation,
    DocumentArtifact,
    GraphArtifact,
    GraphArtifactLink,
    GraphArtifactNode,
    RetrievalChunk,
    RetrievalPayload,
    TableArtifact,
)

logger = logging.getLogger(__name__)

CURRENT_EMITTER: ContextVar[RunEmitter | None] = ContextVar("current_emitter", default=None)
CURRENT_SPECIALIST: ContextVar[str | None] = ContextVar("current_specialist", default=None)
# Set by service.py so case-scoped tools can default to "this case" when the officer
# says "this case" and the LLM passes nothing.
CURRENT_CASE_ID: ContextVar[int | None] = ContextVar("current_case_id", default=None)

MAX_ROWS = 200          # hard cap on any table artifact / raw query
MAX_TRAIL_HOPS = 6      # money-trail recursion depth
MAX_GRAPH_NODES = 120   # force-graph gets unreadable well before this


def _emitter() -> RunEmitter | None:
    return CURRENT_EMITTER.get()


@contextmanager
def _read_session() -> Iterator[Session]:
    """Read-only session: no commit, unlike db.db_session()."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _rows(session: Session, sql: str, **params: Any) -> list[dict[str, Any]]:
    """Run SQL and return dict rows.

    Postgres folds unquoted identifiers to lowercase, so every key here is lowercase
    regardless of how the column is spelled in schema_pg.sql (CaseMasterID ->
    'casemasterid'). Aliasing in the SELECT is the only way to control the key.
    """
    result = session.execute(text(sql), params)
    return [dict(row) for row in result.mappings()]


def _aid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _jsonish(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonish(v) for v in value[:20]]
    if isinstance(value, dict):
        return {str(k): _jsonish(v) for k, v in list(value.items())[:20]}
    return str(value)


def _fmt_inr(amount: Any) -> str:
    """Indian-format an amount the way an IO reads it (lakh/crore)."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    if value >= 1_00_00_000:
        return f"Rs {value / 1_00_00_000:.2f} crore"
    if value >= 1_00_000:
        return f"Rs {value / 1_00_000:.2f} lakh"
    return f"Rs {value:,.0f}"


def _in_thread(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a blocking tool body as an async tool coroutine.

    Also the cancellation boundary: a thread can't be interrupted mid-query, so
    task.cancel() lands between tool calls and during token streaming, never inside a
    running SQL/Cypher statement. That's the honest limit of the Stop button.
    """

    async def run(**kwargs: Any) -> str:
        return await asyncio.to_thread(fn, **kwargs)

    run.__name__ = fn.__name__
    return run


# =============================================================================
# Case resolution -- officers say "129011001202690001", LLMs pass anything
# =============================================================================


def _resolve_case(session: Session, case_ref: str | int | None) -> dict[str, Any] | None:
    """Resolve a CrimeNo, a CaseMasterID, or 'this case' to one CaseMaster row."""
    if case_ref is None or str(case_ref).strip() in ("", "this", "this case", "current"):
        case_id = CURRENT_CASE_ID.get()
        if case_id is None:
            return None
        case_ref = case_id

    ref = str(case_ref).strip()
    # A CrimeNo is an 18-digit string; a CaseMasterID is a 7-digit int. Both are
    # all-digits, so length decides -- checking isdigit alone would send a CrimeNo to
    # the CaseMasterID branch and silently find nothing.
    if ref.isdigit() and len(ref) <= 9:
        rows = _rows(session, "SELECT * FROM CaseMaster WHERE CaseMasterID = :v", v=int(ref))
        if rows:
            return rows[0]
    rows = _rows(session, "SELECT * FROM CaseMaster WHERE CrimeNo = :v", v=ref)
    return rows[0] if rows else None


_CASE_CONTEXT_SQL = """
SELECT c.CaseMasterID AS case_id, c.CrimeNo AS crime_no, c.CrimeRegisteredDate AS registered,
       c.IncidentFromDate AS incident_from, c.BriefFacts AS brief_facts,
       c.Latitude AS lat, c.Longitude AS lon,
       ch.CrimeGroupName AS crime_group, csh.CrimeHeadName AS crime_type,
       g.IncidentDistrict AS district, g.Pincode AS pincode,
       u.UnitName AS police_station
FROM CaseMaster c
LEFT JOIN CrimeHead ch ON ch.CrimeHeadID = c.CrimeMajorHeadID
LEFT JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = c.CrimeMinorHeadID
LEFT JOIN EXT_CaseGeo g ON g.CaseMasterID = c.CaseMasterID
LEFT JOIN Unit u ON u.UnitID = c.PoliceStationID
WHERE c.CaseMasterID = :case_id
"""


# =============================================================================
# SQL agent
# =============================================================================


def get_case_summary(case_ref: str = "") -> str:
    """Full context for one case: parties, charges, timeline, evidence on file."""
    emitter = _emitter()
    with _read_session() as session, _step(emitter, "sql", f"Reading case {case_ref or 'in context'}") as handle:
        case = _resolve_case(session, case_ref)
        if not case:
            handle.output = "not found"
            return f"No case found matching '{case_ref}'. Ask the officer for the CrimeNo."

        case_id = case["casemasterid"]
        ctx = _rows(session, _CASE_CONTEXT_SQL, case_id=case_id)[0]
        handle.query = f"SELECT ... FROM CaseMaster WHERE CaseMasterID = {case_id}"

        complainants = _rows(session, "SELECT ComplainantName AS name, AgeYear AS age, Address AS address FROM ComplainantDetails WHERE CaseMasterID = :c", c=case_id)
        victims = _rows(session, "SELECT VictimName AS name, AgeYear AS age FROM Victim WHERE CaseMasterID = :c", c=case_id)
        accused = _rows(session, "SELECT AccusedName AS name, AgeYear AS age FROM Accused WHERE CaseMasterID = :c", c=case_id)
        charges = _rows(session, """
            SELECT a.ActCode AS act, a.SectionCode AS section, s.SectionDescription AS description
            FROM ActSectionAssociation a
            LEFT JOIN Section s ON s.ActCode = a.ActCode AND s.SectionCode = a.SectionCode
            WHERE a.CaseMasterID = :c ORDER BY a.ActOrderID, a.SectionOrderID
        """, c=case_id)
        timeline = _rows(session, """
            SELECT Label AS label, Timestamp AS at FROM EXT_SubEvent
            WHERE CaseMasterID = :c ORDER BY Timestamp
        """, c=case_id)
        evidence = _rows(session, """
            SELECT doc_type, original_filename, extraction_status FROM Evidence
            WHERE case_id = :c ORDER BY evidence_id
        """, c=case_id)

        if timeline:
            handle.emit_artifact(TableArtifact(
                id=_aid("tbl"), title=f"Case timeline - {ctx['crime_no']}",
                columns=["When", "Event"],
                rows=[[str(t["at"]), t["label"]] for t in timeline[:MAX_ROWS]],
                caption=f"{len(timeline)} recorded sub-events, in sequence.",
            ))

        if ctx["brief_facts"]:
            _cite_text_document(
                emitter,
                label=f"FIR {ctx['crime_no']}",
                source="CaseMaster.BriefFacts",
                text=ctx["brief_facts"] or "",
            )

        handle.output = f"{ctx['crime_no']} - {ctx['crime_type'] or ctx['crime_group']}, {ctx['district']}"

        def _people(rows: list[dict[str, Any]], key: str) -> str:
            return ", ".join("{} ({})".format(r[key], r.get("age")) for r in rows) or "none recorded"

        charge_list = ", ".join("{} {}".format(c["act"], c["section"]) for c in charges) or "none recorded"
        evidence_list = ", ".join(
            "{}:{}".format(e["doc_type"], e["original_filename"]) for e in evidence
        ) or "none"

        lines = [
            f"CASE {ctx['crime_no']} (case_id={case_id})",
            f"  type: {ctx['crime_type'] or ctx['crime_group'] or 'unknown'}",
            f"  district: {ctx['district'] or 'unknown'} (pincode {ctx['pincode'] or '?'})"
            f" | station: {ctx['police_station'] or 'unknown'}",
            f"  registered: {ctx['registered']} | incident from: {ctx['incident_from']}",
            f"  coordinates: {ctx['lat']}, {ctx['lon']}",
            f"  complainants: {_people(complainants, 'name')}",
            f"  victims: {_people(victims, 'name')}",
            f"  accused: {_people(accused, 'name')}",
            f"  charges: {charge_list}",
            f"  evidence on file: {evidence_list}",
            "",
            "BRIEF FACTS:",
            (ctx["brief_facts"] or "(none recorded)"),
        ]
        if timeline:
            lines += ["", "TIMELINE:"] + [f"  {t['at']}  {t['label']}" for t in timeline]
        return "\n".join(lines)


def query_case_stats(
    group_by: str = "district",
    crime_type: str = "",
    district: str = "",
    date_from: str = "",
    date_to: str = "",
) -> str:
    """Counts and trends over cases. group_by: district | crime_type | month | status."""
    emitter = _emitter()
    group_sql = {
        "district": ("g.IncidentDistrict", "District"),
        "crime_type": ("csh.CrimeHeadName", "Crime type"),
        "month": ("to_char(c.CrimeRegisteredDate, 'YYYY-MM')", "Month"),
        "status": ("cs.CaseStatusName", "Status"),
    }
    if group_by not in group_sql:
        return f"group_by must be one of {', '.join(group_sql)} (got '{group_by}')."
    expr, label = group_sql[group_by]

    where = ["1=1"]
    params: dict[str, Any] = {}
    if crime_type:
        where.append("(csh.CrimeHeadName ILIKE :ct OR ch.CrimeGroupName ILIKE :ct)")
        params["ct"] = f"%{crime_type}%"
    if district:
        where.append("g.IncidentDistrict ILIKE :d")
        params["d"] = f"%{district}%"
    if date_from:
        where.append("c.CrimeRegisteredDate >= :df")
        params["df"] = date_from
    if date_to:
        where.append("c.CrimeRegisteredDate <= :dt")
        params["dt"] = date_to

    sql = f"""
        SELECT {expr} AS bucket, COUNT(*) AS cases
        FROM CaseMaster c
        LEFT JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = c.CrimeMinorHeadID
        LEFT JOIN CrimeHead ch ON ch.CrimeHeadID = c.CrimeMajorHeadID
        LEFT JOIN EXT_CaseGeo g ON g.CaseMasterID = c.CaseMasterID
        LEFT JOIN CaseStatusMaster cs ON cs.CaseStatusID = c.CaseStatusID
        WHERE {' AND '.join(where)}
        GROUP BY {expr}
        ORDER BY {'bucket' if group_by == 'month' else 'cases DESC'}
        LIMIT {MAX_ROWS}
    """
    with _read_session() as session, _step(emitter, "sql", f"Aggregating cases by {group_by}") as handle:
        handle.query = " ".join(sql.split())
        rows = _rows(session, sql, **params)
        if not rows:
            handle.output = "0 rows"
            return "No cases match those filters."

        handle.emit_artifact(TableArtifact(
            id=_aid("tbl"), title=f"Cases by {label.lower()}",
            columns=[label, "Cases"],
            rows=[[r["bucket"] or "(unspecified)", r["cases"]] for r in rows],
            caption=" | ".join(filter(None, [
                f"crime type ~ {crime_type}" if crime_type else "",
                f"district ~ {district}" if district else "",
                f"from {date_from}" if date_from else "",
                f"to {date_to}" if date_to else "",
            ])) or "All cases.",
        ))
        total = sum(r["cases"] for r in rows)
        handle.output = f"{len(rows)} buckets, {total} cases"
        body = "\n".join(f"  {r['bucket'] or '(unspecified)'}: {r['cases']}" for r in rows)
        return f"{label} breakdown ({total} cases across {len(rows)} buckets):\n{body}"


# --- guarded raw SQL ---------------------------------------------------------

_SQL_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|"
    r"vacuum|merge|call|do|set|reindex|comment|security|pg_sleep|pg_read_file)\b",
    re.IGNORECASE,
)


def _guard_sql(sql: str) -> str | None:
    """Returns an error string if the SQL isn't a safe single SELECT, else None."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return "Empty query."
    # One statement only: a trailing semicolon is fine (stripped above), but an interior
    # one means a second statement is riding along.
    if ";" in stripped:
        return "Only a single statement is allowed (no ';')."
    if not re.match(r"^\s*(select|with)\b", stripped, re.IGNORECASE):
        return "Only SELECT (or WITH ... SELECT) queries are allowed."
    if _SQL_FORBIDDEN.search(stripped):
        return "Query contains a non-read keyword. This tool is read-only."
    return None


def run_sql_select(sql: str, purpose: str = "") -> str:
    """Run a read-only SELECT against Postgres for questions the other tools don't cover."""
    emitter = _emitter()
    error = _guard_sql(sql)
    if error:
        return f"Rejected: {error}"

    stripped = sql.strip().rstrip(";").strip()
    if not re.search(r"\blimit\s+\d+", stripped, re.IGNORECASE):
        stripped = f"{stripped} LIMIT {MAX_ROWS}"

    with _read_session() as session, _step(emitter, "sql", purpose or "Running database query") as handle:
        handle.query = " ".join(stripped.split())
        try:
            rows = _rows(session, stripped)
        except Exception as exc:
            # Hand the error back rather than raising: the agent can read the message,
            # fix its column names and retry, which is far more useful than a dead run.
            handle.output = "query error"
            return f"SQL error: {str(exc)[:400]}\nCheck column names; identifiers fold to lowercase in Postgres."
        if not rows:
            handle.output = "0 rows"
            return "Query returned no rows."

        columns = list(rows[0].keys())
        handle.emit_artifact(TableArtifact(
            id=_aid("tbl"), title=purpose or "Query result",
            columns=columns,
            rows=[[r.get(c) for c in columns] for r in rows[:MAX_ROWS]],
            caption=f"{len(rows)} row(s).",
        ))
        handle.output = f"{len(rows)} rows"
        preview = "\n".join("  " + " | ".join(f"{c}={r.get(c)}" for c in columns) for r in rows[:30])
        more = f"\n  ... {len(rows) - 30} more rows (shown in the table artifact)" if len(rows) > 30 else ""
        return f"{len(rows)} row(s):\n{preview}{more}"


@contextmanager
def _step(emitter: RunEmitter | None, agent: str, title: str, **kw: Any) -> Iterator[StepHandle]:
    """emitter.step(), tolerating a missing emitter so tools stay unit-testable."""
    if emitter is None:
        yield StepHandle("offline", _NullEmitter())  # type: ignore[arg-type]
        return
    caller = None
    for frame in inspect.stack()[1:8]:
        if frame.function in {"_step", "__enter__", "__exit__"}:
            continue
        if "contextlib.py" in frame.filename.replace("\\", "/"):
            continue
        caller = frame.frame
        break
    tool_name = kw.pop("tool_name", None) or (caller.f_code.co_name if caller else None)
    tool_input = kw.pop("tool_input", None)
    if tool_input is None and caller is not None:
        tool_input = {
            k: _jsonish(v)
            for k, v in caller.f_locals.items()
            if not k.startswith("_") and k not in {"emitter", "session", "handle", "self"}
            and isinstance(v, (str, int, float, bool, list, tuple, dict, type(None)))
        }
    with emitter.step(
        agent, "tool_call", title,
        specialist=CURRENT_SPECIALIST.get(), tool_name=tool_name, tool_input=tool_input,
        **kw,
    ) as handle:  # type: ignore[arg-type]
        yield handle


class _NullEmitter:
    """No-op stand-in so tools can run outside a live run (tests, smoke checks)."""

    def artifact(self, *_a: Any, **_k: Any) -> None: ...
    def citation(self, *_a: Any, **_k: Any) -> None: ...
    def action(self, *_a: Any, **_k: Any) -> None: ...


def _cite_text_document(
    emitter: RunEmitter | None,
    *,
    label: str,
    source: str,
    text: str,
) -> None:
    if not emitter or not text:
        return
    artifact_id = _aid("doc")
    emitter.artifact(DocumentArtifact(
        id=artifact_id, title=label, format="text", text=text,
        caption=source,
    ))
    emitter.citation(AssistantCitation(
        id=_aid("cite"), label=label, source=source,
        document_artifact_id=artifact_id, snippet=text[:280],
    ))


# =============================================================================
# GRAPH agent
# =============================================================================

# Seed accounts for a case: everything the FIR mentions, plus anything the pipeline
# linked to it. Postgres Transaction rows carry no case column (migrate leaves
# source_evidence_id NULL for historical rows), so the case->money entry point has to
# come from the mention/link tables, not from Transaction itself.
_CASE_ACCOUNTS_SQL = """
SELECT DISTINCT a.account_id, a.account_number_raw, a.bank_name, a.branch_district,
       a.is_flagged_mule, a.kyc_name, a.holder_name_raw
FROM Account a
WHERE a.linked_case_id = :case_id
   OR a.account_number_normalized IN (
        SELECT replace(m.object_id, ' ', '') FROM EXT_Mentions m
        WHERE m.case_master_id = :case_id AND lower(m.object_type) = 'accounts'
   )
"""

_ACCOUNTS_BY_NUMBER_SQL = """
SELECT DISTINCT a.account_id, a.account_number_raw, a.bank_name, a.branch_district,
       a.is_flagged_mule, a.kyc_name, a.holder_name_raw
FROM Account a
WHERE a.account_number_normalized = ANY(:numbers)
"""

_CASE_ACCOUNT_MENTIONS_CYPHER = """
MATCH (c:CaseMaster {case_id: $case_id})-[:MENTIONS]->(a:Account)
RETURN a.display_name AS account_number
"""

# Walks transfers forward from the seed accounts. Depth-capped rather than
# cycle-detected: mule rings really do contain cycles, and a bounded hop count is both
# simpler and closer to how an IO reads a trail ("three hops out from the victim").
_TRAIL_SQL = f"""
WITH RECURSIVE trail AS (
    SELECT t.txn_id, t.from_account_id, t.to_account_id, t.to_wallet_address,
           t.amount, t.txn_timestamp, t.mode, t.utr_ref, 1 AS hop
    FROM Transaction t
    WHERE t.from_account_id = ANY(:seed_ids)
    UNION ALL
    SELECT t.txn_id, t.from_account_id, t.to_account_id, t.to_wallet_address,
           t.amount, t.txn_timestamp, t.mode, t.utr_ref, tr.hop + 1
    FROM Transaction t
    JOIN trail tr ON t.from_account_id = tr.to_account_id
    WHERE tr.hop < {MAX_TRAIL_HOPS}
      AND t.to_account_id IS DISTINCT FROM t.from_account_id
)
SELECT DISTINCT ON (txn_id) txn_id, from_account_id, to_account_id, to_wallet_address,
       amount, txn_timestamp, mode, utr_ref, hop
FROM trail
ORDER BY txn_id, hop
"""

_INBOUND_TO_SEEDS_SQL = """
SELECT t.txn_id, t.from_account_id, t.to_account_id, t.to_wallet_address,
       t.amount, t.txn_timestamp, t.mode, t.utr_ref, 0 AS hop
FROM Transaction t
WHERE t.to_account_id = ANY(:seed_ids)
ORDER BY t.txn_timestamp NULLS LAST, t.txn_id
"""


def _account_labels(session: Session, account_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not account_ids:
        return {}
    rows = _rows(session, """
        SELECT account_id, account_number_raw, bank_name, branch_district,
               is_flagged_mule, kyc_name, holder_name_raw
        FROM Account WHERE account_id = ANY(:ids)
    """, ids=account_ids)
    return {r["account_id"]: r for r in rows}


def _case_accounts_from_graph(session: Session, case_id: int) -> list[dict[str, Any]]:
    try:
        rows = stores.run_cypher(_CASE_ACCOUNT_MENTIONS_CYPHER, case_id=int(case_id))
    except Exception:
        logger.debug("money trail: graph account seed fallback failed", exc_info=True)
        return []
    numbers = [
        "".join(str(r.get("account_number") or "").split())
        for r in rows
        if r.get("account_number")
    ]
    if not numbers:
        return []
    return _rows(session, _ACCOUNTS_BY_NUMBER_SQL, numbers=numbers)


def trace_money_flow(case_ref: str = "", account_number: str = "") -> str:
    """Follow the money out of a case (or one account), in time order, and flag funds
    that arrived but never left (still freezable)."""
    emitter = _emitter()
    with _read_session() as session, _step(emitter, "graph", "Tracing the money trail") as handle:
        seeds: list[dict[str, Any]] = []
        title_ref = ""
        if account_number:
            normalized = "".join(str(account_number).split())
            seeds = _rows(session, """
                SELECT account_id, account_number_raw, bank_name, branch_district,
                       is_flagged_mule, kyc_name, holder_name_raw
                FROM Account WHERE account_number_normalized = :n
            """, n=normalized)
            title_ref = f"A/c {account_number}"
        else:
            case = _resolve_case(session, case_ref)
            if not case:
                handle.output = "case not found"
                return f"No case found matching '{case_ref}'."
            seeds = _rows(session, _CASE_ACCOUNTS_SQL, case_id=case["casemasterid"])
            if not seeds:
                seeds = _case_accounts_from_graph(session, int(case["casemasterid"]))
            title_ref = str(case["crimeno"])

        if not seeds:
            handle.output = "no accounts"
            return f"No bank accounts are linked to {title_ref}, so there is no trail to walk."

        seed_ids = [s["account_id"] for s in seeds]
        handle.query = f"WITH RECURSIVE trail AS (...) -- seeds: {seed_ids}, max {MAX_TRAIL_HOPS} hops"
        txns = _rows(session, _TRAIL_SQL, seed_ids=seed_ids)
        if not txns:
            txns = _rows(session, _INBOUND_TO_SEEDS_SQL, seed_ids=seed_ids)
            handle.query = f"SELECT inbound transfers TO seed accounts -- seeds: {seed_ids}"
        if not txns:
            handle.output = "no transfers"
            return f"{title_ref} has linked accounts but no transfers recorded around those accounts."

        txns.sort(key=lambda t: (t["txn_timestamp"] is None, t["txn_timestamp"]))

        involved = {t["from_account_id"] for t in txns} | {t["to_account_id"] for t in txns}
        involved.discard(None)
        labels = _account_labels(session, list(involved) + seed_ids)

        # Freezable = money that arrived and has not moved on since. Compare each
        # account's last inbound against its last outbound; that's the golden-hour
        # question ("what can I still freeze?").
        last_in: dict[int, Any] = {}
        last_out: dict[int, Any] = {}
        inflow: dict[int, float] = {}
        outflow: dict[int, float] = {}
        for t in txns:
            amount = float(t["amount"] or 0)
            if t["to_account_id"]:
                inflow[t["to_account_id"]] = inflow.get(t["to_account_id"], 0) + amount
                if t["txn_timestamp"] and (t["to_account_id"] not in last_in or t["txn_timestamp"] > last_in[t["to_account_id"]]):
                    last_in[t["to_account_id"]] = t["txn_timestamp"]
            if t["from_account_id"]:
                outflow[t["from_account_id"]] = outflow.get(t["from_account_id"], 0) + amount
                if t["txn_timestamp"] and (t["from_account_id"] not in last_out or t["txn_timestamp"] > last_out[t["from_account_id"]]):
                    last_out[t["from_account_id"]] = t["txn_timestamp"]

        freezable: list[tuple[int, float]] = []
        for account_id, received in inflow.items():
            out_at = last_out.get(account_id)
            in_at = last_in.get(account_id)
            if in_at and (out_at is None or out_at < in_at):
                still_held = received - outflow.get(account_id, 0.0)
                if still_held > 0:
                    freezable.append((account_id, still_held))
        freezable.sort(key=lambda x: -x[1])

        def _node_label(account_id: int) -> str:
            row = labels.get(account_id)
            if not row:
                return f"A/c #{account_id}"
            who = row.get("kyc_name") or row.get("holder_name_raw")
            acc = row.get("account_number_raw") or account_id
            return f"{who} - {acc}" if who else str(acc)

        nodes: list[GraphArtifactNode] = []
        seen: set[str] = set()

        def _add_account(account_id: int) -> str:
            node_id = f"acc:{account_id}"
            if node_id in seen:
                return node_id
            seen.add(node_id)
            row = labels.get(account_id, {})
            is_seed = account_id in seed_ids
            frozen = dict(freezable).get(account_id)
            nodes.append(GraphArtifactNode(
                id=node_id, label=_node_label(account_id),
                # Node type drives colour + legend in GraphArtifactView, so it carries
                # the finding (origin/mule/freezable), not just the entity class.
                type="Victim" if is_seed else ("Freezable" if frozen else ("Mule" if row.get("is_flagged_mule") else "Account")),
                properties={k: v for k, v in {
                    "bank": row.get("bank_name"), "district": row.get("branch_district"),
                    "received": _fmt_inr(inflow.get(account_id, 0)) if inflow.get(account_id) else None,
                    "still_held": _fmt_inr(frozen) if frozen else None,
                }.items() if v},
            ))
            return node_id

        links: list[GraphArtifactLink] = []
        for t in txns[:MAX_GRAPH_NODES]:
            if not t["from_account_id"]:
                continue
            src = _add_account(t["from_account_id"])
            if t["to_account_id"]:
                dst = _add_account(t["to_account_id"])
            elif t["to_wallet_address"]:
                dst = f"wallet:{t['to_wallet_address']}"
                if dst not in seen:
                    seen.add(dst)
                    nodes.append(GraphArtifactNode(
                        id=dst, label=f"Crypto wallet {str(t['to_wallet_address'])[:12]}...",
                        type="Wallet", properties={"address": t["to_wallet_address"], "channel": t["mode"] or "crypto"},
                    ))
            else:
                continue
            links.append(GraphArtifactLink(
                source=src, target=dst, relationship=_fmt_inr(t["amount"]),
                properties={k: v for k, v in {
                    "amount": float(t["amount"] or 0), "when": str(t["txn_timestamp"]),
                    "mode": t["mode"], "utr": t["utr_ref"], "hop": t["hop"],
                }.items() if v is not None},
            ))

        handle.emit_artifact(GraphArtifact(
            id=_aid("graph"), title=f"Money trail - {title_ref}", nodes=nodes, links=links,
            caption=f"{len(txns)} transfers across {len(nodes)} accounts, up to {MAX_TRAIL_HOPS} hops.",
        ))
        handle.emit_artifact(TableArtifact(
            id=_aid("tbl"), title=f"Transfers in time order - {title_ref}",
            columns=["When", "From", "To", "Amount", "Mode", "Hop"],
            rows=[[
                str(t["txn_timestamp"]), _node_label(t["from_account_id"]),
                _node_label(t["to_account_id"]) if t["to_account_id"] else f"wallet {t['to_wallet_address']}",
                _fmt_inr(t["amount"]), t["mode"] or "", t["hop"],
            ] for t in txns[:MAX_ROWS]],
            caption="Ordered by transaction timestamp.",
        ))

        total = sum(float(t["amount"] or 0) for t in txns)
        first, last = txns[0]["txn_timestamp"], txns[-1]["txn_timestamp"]
        span = ""
        try:
            minutes = (last - first).total_seconds() / 60
            span = f" The whole trail completed in {minutes:.0f} minutes."
        except Exception:
            pass

        freeze_lines = [
            f"  {_node_label(aid)}: {_fmt_inr(amt)} received with no onward transfer since {last_in.get(aid)}"
            for aid, amt in freezable[:10]
        ]
        wallets = {t["to_wallet_address"] for t in txns if t["to_wallet_address"]}

        out = [
            f"MONEY TRAIL for {title_ref}",
            f"  {len(txns)} transfers totalling {_fmt_inr(total)} across {len(nodes)} accounts.",
            f"  first: {first}  last: {last}.{span}",
        ]
        if wallets:
            out.append(f"  CASH-OUT: funds reached crypto wallet(s) {', '.join(str(w) for w in wallets)} - outside banking jurisdiction.")
        if freeze_lines:
            out += [
                f"  POTENTIALLY FREEZABLE - {_fmt_inr(sum(a for _, a in freezable))} sitting still:",
                *freeze_lines,
            ]
        else:
            out.append("  No freezable funds: every account that received money has already moved it on.")
        handle.output = f"{len(txns)} transfers, {_fmt_inr(total)}, {len(freezable)} freezable"
        return "\n".join(out)


def find_links_between_cases(case_refs: list[str]) -> str:
    """Find objects (accounts, UPIs, devices, phones, IPs) shared by two or more cases --
    the structural link behind 'separate' investigations."""
    emitter = _emitter()
    with _read_session() as session, _step(emitter, "graph", "Searching for shared identifiers") as handle:
        case_ids: list[int] = []
        crime_by_id: dict[int, str] = {}
        for ref in case_refs:
            case = _resolve_case(session, ref)
            if case:
                case_ids.append(int(case["casemasterid"]))
                crime_by_id[int(case["casemasterid"])] = str(case["crimeno"])
        if len(case_ids) < 2:
            handle.output = "need 2+ cases"
            return f"Need at least two resolvable cases to compare; resolved {len(case_ids)} of {len(case_refs)}."

        cypher = """
        MATCH (c1:CaseMaster)-[:MENTIONS]->(o)<-[:MENTIONS]-(c2:CaseMaster)
        WHERE c1.case_id IN $ids AND c2.case_id IN $ids AND c1.case_id < c2.case_id
        RETURN o.entity_uid AS uid, o.display_name AS name, labels(o) AS labels,
               collect(DISTINCT c1.case_id) + collect(DISTINCT c2.case_id) AS cases
        """
        handle.query = " ".join(cypher.split())
        rows = stores.run_cypher(cypher, ids=case_ids)
        if not rows:
            handle.output = "no shared objects"
            return (f"No shared accounts, devices, UPIs, phones or IPs among cases "
                    f"{', '.join(crime_by_id.values())}. They look genuinely unrelated on the identifiers we hold.")

        shared: dict[str, dict[str, Any]] = {}
        for r in rows:
            entry = shared.setdefault(r["uid"], {"name": r["name"], "labels": r["labels"], "cases": set()})
            entry["cases"].update(r["cases"])

        nodes: list[GraphArtifactNode] = []
        links: list[GraphArtifactLink] = []
        for case_id in case_ids:
            nodes.append(GraphArtifactNode(
                id=f"case:{case_id}", label=crime_by_id.get(case_id, str(case_id)), type="Crime",
                properties={"case_id": case_id},
            ))
        for uid, entry in shared.items():
            # The dynamic live labels mean an object can be :Account:BankStatement; take
            # the first label the historical loader assigns so colours stay stable.
            kind = next((l for l in entry["labels"] if l in
                         ("Account", "UPIHandle", "Device", "PhoneNumber", "IP", "Wallet")), "Object")
            nodes.append(GraphArtifactNode(
                id=f"obj:{uid}", label=entry["name"] or kind, type=kind,
                properties={"shared_by": len(entry["cases"])},
            ))
            for case_id in entry["cases"]:
                links.append(GraphArtifactLink(
                    source=f"case:{case_id}", target=f"obj:{uid}", relationship="MENTIONS",
                ))

        handle.emit_artifact(GraphArtifact(
            id=_aid("graph"), title="Shared identifiers across cases", nodes=nodes, links=links,
            caption=f"{len(shared)} object(s) referenced by more than one of {len(case_ids)} cases.",
        ))

        lines = []
        for uid, entry in sorted(shared.items(), key=lambda kv: -len(kv[1]["cases"])):
            kind = next((l for l in entry["labels"] if l != "Object"), "Object")
            refs = ", ".join(crime_by_id.get(c, str(c)) for c in sorted(entry["cases"]))
            lines.append(f"  {kind} {entry['name']} -> shared by {len(entry['cases'])} cases: {refs}")
        handle.output = f"{len(shared)} shared object(s)"
        return (f"SHARED IDENTIFIERS across {len(case_ids)} cases "
                f"({', '.join(crime_by_id.values())}):\n" + "\n".join(lines))


def expand_entity(value: str, max_hops: int = 2) -> str:
    """Show the neighbourhood of any identifier (account no, UPI, IMEI, phone, IP)."""
    emitter = _emitter()
    with _step(_emitter(), "graph", f"Expanding {value}") as handle:
        normalized = "".join(str(value).split())
        hops = max(1, min(int(max_hops or 2), 3))
        cypher = f"""
        MATCH (n)
        WHERE n.display_name = $v OR n.display_name CONTAINS $v
        WITH n LIMIT 5
        MATCH path = (n)-[*1..{hops}]-(m)
        WITH n, m, relationships(path) AS rels
        RETURN DISTINCT n.entity_uid AS from_uid, n.display_name AS from_name, labels(n) AS from_labels,
               m.entity_uid AS to_uid, m.display_name AS to_name, labels(m) AS to_labels,
               [r IN rels | type(r)] AS rel_types
        LIMIT {MAX_GRAPH_NODES}
        """
        handle.query = " ".join(cypher.split())
        rows = stores.run_cypher(cypher, v=normalized)
        if not rows:
            handle.output = "not found"
            return f"'{value}' does not appear in the graph. It may not have been extracted, or the format may differ."

        nodes: dict[str, GraphArtifactNode] = {}
        links: list[GraphArtifactLink] = []

        def _put(uid: str, name: str, labels: list[str]) -> None:
            if uid and uid not in nodes:
                kind = next((l for l in labels if l in
                             ("CaseMaster", "Account", "UPIHandle", "Device", "PhoneNumber",
                              "IP", "Wallet", "Accused", "Victim", "ComplainantDetails")), "Object")
                nodes[uid] = GraphArtifactNode(id=uid, label=name or kind, type=kind)

        for r in rows:
            _put(r["from_uid"], r["from_name"], r["from_labels"])
            _put(r["to_uid"], r["to_name"], r["to_labels"])
            if r["from_uid"] and r["to_uid"] and r["from_uid"] != r["to_uid"]:
                links.append(GraphArtifactLink(
                    source=r["from_uid"], target=r["to_uid"],
                    relationship=" > ".join(r["rel_types"] or ["LINKED"]),
                ))

        handle.emit_artifact(GraphArtifact(
            id=_aid("graph"), title=f"Neighbourhood of {value}",
            nodes=list(nodes.values()), links=links,
            caption=f"Up to {hops} hop(s) from {value}.",
        ))
        handle.output = f"{len(nodes)} nodes, {len(links)} links"
        summary = "\n".join(
            f"  {r['from_name']} -[{' > '.join(r['rel_types'] or [])}]- {r['to_name']} ({', '.join(r['to_labels'])})"
            for r in rows[:40]
        )
        return f"NEIGHBOURHOOD of {value} ({len(nodes)} nodes within {hops} hops):\n{summary}"


def person_history(name: str) -> str:
    """Every case tied to a person, plus the identifiers that tie their aliases together."""
    emitter = _emitter()
    with _read_session() as session, _step(emitter, "graph", f"Building history for {name}") as handle:
        # Shared identifiers are what collapse aliases: match the person by name, then
        # walk OWNS to their objects and back out to everyone else using the same ones.
        cypher = """
        MATCH (p)-[:OWNS]->(o)
        WHERE (p:Accused OR p:Victim OR p:ComplainantDetails)
          AND toLower(p.display_name) CONTAINS toLower($name)
        WITH collect(DISTINCT o.entity_uid) AS objs
        MATCH (other)-[:OWNS]->(o2)
        WHERE o2.entity_uid IN objs AND (other:Accused OR other:Victim OR other:ComplainantDetails)
        RETURN DISTINCT other.entity_uid AS uid, other.display_name AS name,
               other.case_id AS case_id, labels(other) AS labels,
               [(other)-[:OWNS]->(x) | {name: x.display_name, kind: labels(x)[0]}] AS objects
        """
        handle.query = " ".join(cypher.split())
        rows = stores.run_cypher(cypher, name=name)
        if not rows:
            handle.output = "no identifier links"
            return (f"No person matching '{name}' owns identifiers we can link on. "
                    f"They may appear only by name, with no shared device/UPI/phone.")

        case_ids = [r["case_id"] for r in rows if r["case_id"]]
        cases = _rows(session, """
            SELECT c.CaseMasterID AS case_id, c.CrimeNo AS crime_no, c.CrimeRegisteredDate AS registered,
                   csh.CrimeHeadName AS crime_type, g.IncidentDistrict AS district
            FROM CaseMaster c
            LEFT JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = c.CrimeMinorHeadID
            LEFT JOIN EXT_CaseGeo g ON g.CaseMasterID = c.CaseMasterID
            WHERE c.CaseMasterID = ANY(:ids) ORDER BY c.CrimeRegisteredDate
        """, ids=case_ids) if case_ids else []

        aliases = sorted({r["name"] for r in rows if r["name"]})
        shared_objects = sorted({(o["kind"], o["name"]) for r in rows for o in (r["objects"] or [])})

        handle.emit_artifact(TableArtifact(
            id=_aid("tbl"), title=f"Case history - {name}",
            columns=["Registered", "CrimeNo", "Type", "District", "Recorded as"],
            rows=[[
                str(c["registered"]), c["crime_no"], c["crime_type"] or "", c["district"] or "",
                next((r["name"] for r in rows if r["case_id"] == c["case_id"]), ""),
            ] for c in cases],
            caption=f"{len(cases)} case(s), oldest first.",
        ))

        handle.output = f"{len(aliases)} identities, {len(cases)} cases"
        out = [
            f"PERSON HISTORY for '{name}'",
            f"  {len(aliases)} record(s) linked by shared identifiers: {', '.join(aliases)}",
            f"  linked by: {', '.join('{} {}'.format(k, n) for k, n in shared_objects)}",
            "",
            "CASES (oldest first):",
        ]
        for c in cases:
            out.append(f"  {c['registered']}  {c['crime_no']}  {c['crime_type'] or '?'}  {c['district'] or '?'}")
        out.append("")
        out.append("Note: identity linkage is evidence for review, not proof. Each link is a shared "
                   "device/UPI/phone recorded in the case file.")
        return "\n".join(out)


def detect_community(case_refs: list[str] | None = None, crime_type: str = "", days: int = 0) -> str:
    """Cluster cases that share infrastructure, and rank the most central objects --
    'is this one organised ring, or copycats?'"""
    emitter = _emitter()
    with _read_session() as session, _step(emitter, "graph", "Clustering cases by shared infrastructure") as handle:
        case_ids: list[int] = []
        if case_refs:
            for ref in case_refs:
                case = _resolve_case(session, ref)
                if case:
                    case_ids.append(int(case["casemasterid"]))
        else:
            where = ["1=1"]
            params: dict[str, Any] = {}
            if crime_type:
                where.append("(csh.CrimeHeadName ILIKE :ct OR ch.CrimeGroupName ILIKE :ct)")
                params["ct"] = f"%{crime_type}%"
            if days:
                where.append("c.CrimeRegisteredDate >= NOW() - (:d || ' days')::interval")
                params["d"] = str(int(days))
            case_ids = [r["case_id"] for r in _rows(session, f"""
                SELECT c.CaseMasterID AS case_id FROM CaseMaster c
                LEFT JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = c.CrimeMinorHeadID
                LEFT JOIN CrimeHead ch ON ch.CrimeHeadID = c.CrimeMajorHeadID
                WHERE {' AND '.join(where)} LIMIT 500
            """, **params)]

        if len(case_ids) < 2:
            handle.output = "too few cases"
            return "Need at least two cases to look for a community."

        cypher = """
        MATCH (c:CaseMaster)-[:MENTIONS]->(o)
        WHERE c.case_id IN $ids
        RETURN o.entity_uid AS uid, o.display_name AS name, labels(o) AS labels,
               collect(DISTINCT c.case_id) AS cases
        """
        handle.query = " ".join(cypher.split())
        rows = stores.run_cypher(cypher, ids=case_ids)
        # Union-find over "cases sharing an object": no GDS on Aura, and Louvain would be
        # overkill for connectivity anyway -- shared infrastructure IS the edge here.
        parent: dict[int, int] = {c: c for c in case_ids}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for r in rows:
            members = [c for c in r["cases"] if c in parent]
            for other in members[1:]:
                union(members[0], other)

        clusters: dict[int, list[int]] = {}
        for case_id in case_ids:
            clusters.setdefault(find(case_id), []).append(case_id)
        ranked = sorted(clusters.values(), key=len, reverse=True)
        biggest = ranked[0] if ranked else []

        # Degree centrality, plainly: how many of this cluster's cases touch each object.
        central = sorted(
            ({"name": r["name"], "labels": r["labels"], "n": len([c for c in r["cases"] if c in biggest])}
             for r in rows),
            key=lambda x: -x["n"],
        )[:10]

        crime_nos = {r["case_id"]: r["crime_no"] for r in _rows(
            session, "SELECT CaseMasterID AS case_id, CrimeNo AS crime_no FROM CaseMaster WHERE CaseMasterID = ANY(:ids)",
            ids=case_ids)}

        handle.emit_artifact(TableArtifact(
            id=_aid("tbl"), title="Most connected shared objects",
            columns=["Object", "Type", "Cases in cluster touching it"],
            rows=[[c["name"], next((l for l in c["labels"] if l != "Object"), "?"), c["n"]]
                  for c in central if c["n"] > 1],
            caption=f"Largest cluster spans {len(biggest)} of {len(case_ids)} cases.",
        ))

        handle.output = f"{len(ranked)} clusters, largest {len(biggest)}"
        singletons = sum(1 for c in ranked if len(c) == 1)
        out = [
            f"COMMUNITY ANALYSIS over {len(case_ids)} cases",
            f"  {len(ranked)} cluster(s); largest holds {len(biggest)} cases; {singletons} unconnected.",
        ]
        if len(biggest) > 1:
            out.append(f"  Largest cluster: {', '.join(str(crime_nos.get(c, c)) for c in biggest[:20])}")
            out.append("  Shared infrastructure ranking them together:")
            out += [f"    {c['name']} ({next((l for l in c['labels'] if l != 'Object'), '?')}) - in {c['n']} of them"
                    for c in central if c["n"] > 1]
            out.append("  A cluster this size sharing infrastructure is consistent with one operation "
                       "rather than copycats - but it is an investigative lead, not proof.")
        else:
            out.append("  No case shares infrastructure with another: these look like independent incidents.")
        return "\n".join(out)


# --- guarded raw Cypher ------------------------------------------------------

_CYPHER_FORBIDDEN = re.compile(
    r"\b(create|merge|delete|detach|set|remove|drop|load\s+csv|foreach|"
    r"call\s*\{|apoc\.|dbms\.|db\.index|periodic)\b",
    re.IGNORECASE,
)


def _guard_cypher(cypher: str) -> str | None:
    stripped = cypher.strip().rstrip(";").strip()
    if not stripped:
        return "Empty query."
    if ";" in stripped:
        return "Only a single statement is allowed (no ';')."
    if not re.match(r"^\s*(match|with|unwind|return|optional\s+match|profile|explain)\b", stripped, re.IGNORECASE):
        return "Query must start with MATCH/WITH/UNWIND/RETURN."
    if _CYPHER_FORBIDDEN.search(stripped):
        return "Query contains a write or procedure clause. This tool is read-only."
    return None


def run_cypher_read(cypher: str, purpose: str = "") -> str:
    """Run a read-only Cypher query for graph questions the other tools don't cover."""
    emitter = _emitter()
    error = _guard_cypher(cypher)
    if error:
        return f"Rejected: {error}"
    stripped = cypher.strip().rstrip(";").strip()
    if not re.search(r"\blimit\s+\d+", stripped, re.IGNORECASE):
        stripped = f"{stripped} LIMIT {MAX_ROWS}"

    with _step(emitter, "graph", purpose or "Running graph query") as handle:
        handle.query = " ".join(stripped.split())
        try:
            # stores.run_cypher uses execute_read, so a write clause that slipped past
            # the regex still fails at the transaction level.
            rows = stores.run_cypher(stripped)
        except Exception as exc:
            handle.output = "query error"
            return (f"Cypher error: {str(exc)[:400]}\n"
                    f"Labels: CaseMaster, Accused, Victim, ComplainantDetails, Account, UPIHandle, "
                    f"Device, PhoneNumber, IP, Wallet, InvestigationReport. "
                    f"Rels: MENTIONS, INVOLVES, OWNS, TRANSACTED_WITH, HAS_EVIDENCE.")
        if not rows:
            handle.output = "0 rows"
            return "Query returned no rows."

        columns = list(rows[0].keys())
        handle.emit_artifact(TableArtifact(
            id=_aid("tbl"), title=purpose or "Graph query result",
            columns=columns,
            rows=[[str(r.get(c)) if isinstance(r.get(c), (list, dict)) else r.get(c) for c in columns]
                  for r in rows[:MAX_ROWS]],
            caption=f"{len(rows)} row(s).",
        ))
        handle.output = f"{len(rows)} rows"
        preview = "\n".join("  " + " | ".join(f"{c}={r.get(c)}" for c in columns) for r in rows[:30])
        return f"{len(rows)} row(s):\n{preview}"


# =============================================================================
# VECTOR agent
# =============================================================================


def find_similar_cases(case_ref: str = "", text_query: str = "", top_k: int = 5) -> str:
    """Find cases with the same modus operandi by meaning, not keywords."""
    emitter = _emitter()
    with _read_session() as session, _step(emitter, "vector", "Searching narratives by meaning") as handle:
        query_text = text_query
        exclude_case_id: int | None = None
        source_ref = text_query[:60]
        if case_ref and not text_query:
            case = _resolve_case(session, case_ref)
            if not case:
                handle.output = "case not found"
                return f"No case found matching '{case_ref}'."
            exclude_case_id = int(case["casemasterid"])
            query_text = case.get("brieffacts") or ""
            source_ref = str(case["crimeno"])
            if not query_text:
                handle.output = "no narrative"
                return f"Case {source_ref} has no narrative text to match on."
        if not query_text:
            return "Provide either case_ref or text_query."

        k = max(1, min(int(top_k or 5), 20))
        handle.query = f"vector similarity over FIR narratives, top {k} (Titan 1536-d, cosine)"
        vector = stores.embed(query_text)
        # Over-fetch: the source case's own chunks rank top and get dropped below.
        result = stores.pinecone_index().query(
            vector=vector, top_k=k + 6, include_metadata=True,
        )

        seen_cases: dict[int, dict[str, Any]] = {}
        for match in result.get("matches", []):
            meta = match.get("metadata") or {}
            raw_case = meta.get("case_id")
            if raw_case is None:
                continue
            case_id = int(float(raw_case))
            if case_id == exclude_case_id or case_id in seen_cases:
                continue
            seen_cases[case_id] = {"score": float(match.get("score") or 0), "meta": meta}
            if len(seen_cases) >= k:
                break

        if not seen_cases:
            handle.output = "no matches"
            return f"No similar cases found for {source_ref}."

        rows = _rows(session, """
            SELECT c.CaseMasterID AS case_id, c.CrimeNo AS crime_no, c.BriefFacts AS brief_facts,
                   c.CrimeRegisteredDate AS registered,
                   csh.CrimeHeadName AS crime_type, g.IncidentDistrict AS district
            FROM CaseMaster c
            LEFT JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = c.CrimeMinorHeadID
            LEFT JOIN EXT_CaseGeo g ON g.CaseMasterID = c.CaseMasterID
            WHERE c.CaseMasterID = ANY(:ids)
        """, ids=list(seen_cases))
        by_id = {r["case_id"]: r for r in rows}

        ranked = sorted(seen_cases.items(), key=lambda kv: -kv[1]["score"])
        handle.emit_artifact(TableArtifact(
            id=_aid("tbl"), title=f"Cases similar to {source_ref}",
            columns=["Score", "CrimeNo", "Type", "District", "Registered"],
            rows=[[
                round(v["score"], 3), (by_id.get(cid) or {}).get("crime_no", cid),
                (by_id.get(cid) or {}).get("crime_type", ""),
                (by_id.get(cid) or {}).get("district", ""),
                str((by_id.get(cid) or {}).get("registered", "")),
            ] for cid, v in ranked],
            caption="Cosine similarity over FIR narrative embeddings.",
        ))
        emitter and emitter.retrieval(RetrievalPayload(
            step_id=handle.id,
            mode="vector_similarity",
            query=handle.query or "",
            count=len(ranked),
            sources=[
                str((by_id.get(cid) or {}).get("crime_no", cid))
                for cid, _ in ranked
            ],
            chunks=[
                RetrievalChunk(
                    case_ref=str((by_id.get(cid) or {}).get("crime_no", cid)),
                    source=(by_id.get(cid) or {}).get("district"),
                    score=round(v["score"], 3),
                    snippet=((by_id.get(cid) or {}).get("brief_facts") or "")[:220],
                )
                for cid, v in ranked
            ],
        ))
        for cid, v in ranked[:3]:
            row = by_id.get(cid)
            if row and row.get("brief_facts"):
                _cite_text_document(
                    emitter,
                    label=f"FIR {row['crime_no']}",
                    source=f"similarity {v['score']:.2f}",
                    text=row["brief_facts"],
                )

        # The "Find Links" move: hand the agent the case refs and offer the officer the
        # follow-up in one click.
        refs = [str((by_id.get(cid) or {}).get("crime_no", cid)) for cid, _ in ranked]
        all_refs = ([source_ref] if exclude_case_id else []) + refs
        emitter and emitter.action(AssistantAction(
            id=_aid("act"), label="Find links among these cases", icon="link",
            prompt=f"Find links among these cases: {', '.join(all_refs)}",
        ))

        districts = {(by_id.get(cid) or {}).get("district") for cid, _ in ranked}
        out = [f"SIMILAR CASES to {source_ref} ({len(ranked)} matches):"]
        for cid, v in ranked:
            row = by_id.get(cid, {})
            out.append(f"  {v['score']:.2f}  {row.get('crime_no', cid)}  {row.get('crime_type') or '?'}  "
                       f"{row.get('district') or '?'}  ({row.get('registered')})")
        if len([d for d in districts if d]) > 1:
            out.append(f"  Spread across {len([d for d in districts if d])} districts: "
                       f"{', '.join(str(d) for d in districts if d)} - a cross-jurisdiction pattern.")
        out.append(f"  Case refs for link analysis: {', '.join(all_refs)}")
        handle.output = f"{len(ranked)} matches, top {ranked[0][1]['score']:.2f}"
        return "\n".join(out)


# =============================================================================
# LEGAL agent
#
# The whole chain lives in Postgres (the legal layer is not loaded into Neo4j):
#   ActSectionAssociation -> EXT_SectionMap -> EXT_LegalElement
#                         -> EXT_ElementSatisfiedBy -> EXT_EvidenceType
#                         -> EXT_Precedent
# EXT_SectionMap is the bridge: charges are keyed (ActCode, SectionCode), the legal
# layer keys on SectionID.
# =============================================================================

_CHECKLIST_SQL = """
SELECT asa.ActCode AS act, asa.SectionCode AS section, sm.SectionID AS section_id,
       s.SectionDescription AS section_desc,
       le.ElementID AS element_id, le.Name AS element, le.Description AS element_desc,
       et.EvidenceTypeID AS evidence_type_id, et.Name AS evidence_name,
       et.Requires63Certificate AS needs_63
FROM ActSectionAssociation asa
JOIN EXT_SectionMap sm ON sm.ActCode = asa.ActCode AND sm.SectionCode = asa.SectionCode
LEFT JOIN Section s ON s.ActCode = asa.ActCode AND s.SectionCode = asa.SectionCode
JOIN EXT_LegalElement le ON le.SectionID = sm.SectionID
LEFT JOIN EXT_ElementSatisfiedBy esb ON esb.ElementID = le.ElementID
LEFT JOIN EXT_EvidenceType et ON et.EvidenceTypeID = esb.EvidenceTypeID
WHERE asa.CaseMasterID = :case_id
ORDER BY asa.ActOrderID, asa.SectionOrderID, le.ElementID
"""

# Maps an uploaded document to the evidence types it can stand as. Keyed off what the
# pipeline actually records (Evidence.doc_type / original_filename) rather than a
# per-scenario script, so an unseen upload still classifies.
_EVIDENCE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("ET_SCREENSHOT", ("screenshot", "whatsapp", "telegram", "skype", "messaging", "chat")),
    ("ET_BANK_STMT", ("bank", "statement", "ledger", "transaction_ledger", "account_details")),
    ("ET_TXN_RECEIPT", ("receipt", "txn", "payment", "upi_txn")),
    ("ET_CDR", ("cdr", "call_log", "call log", "call_record")),
    ("ET_DEVICE_DUMP", ("device_forensic", "forensics", "device_dump", "dump", "device_pool")),
    ("ET_KYC", ("kyc", "aadhaar", "pan")),
    ("ET_CRYPTO_TXN", ("crypto", "wallet", "usdt", "chain")),
    ("ET_IP_LOG", ("ip_log", "server_log", "login_log")),
    ("ET_VICTIM_STMT", ("victim_statement", "complaint", "fir")),
    ("ET_WITNESS_STMT", ("witness",)),
    ("ET_IMEI_REG", ("imei", "ceir", "tafcop")),
    ("ET_UPI_LOG", ("upi", "npci", "vpa")),
    ("ET_EMAIL", ("email", "mail")),
    ("ET_SOCIAL_MEDIA", ("social", "facebook", "instagram", "profile")),
]

_CERT_HINTS = ("bsa_63", "bsa63", "63_certificate", "certificate_63", "section_63", "s63")


def _classify_evidence(session: Session, case_id: int) -> tuple[set[str], bool, list[dict[str, Any]]]:
    """Returns (evidence types present, a s63 certificate is on file, raw evidence rows)."""
    rows = _rows(session, """
        SELECT doc_type, original_filename, file_ref, extraction_status
        FROM Evidence WHERE case_id = :c ORDER BY evidence_id
    """, c=case_id)
    present: set[str] = set()
    has_cert = False
    for row in rows:
        blob = " ".join(str(row.get(k) or "").lower() for k in ("doc_type", "original_filename", "file_ref"))
        if any(h in blob for h in _CERT_HINTS):
            has_cert = True
        for type_id, hints in _EVIDENCE_HINTS:
            if any(h in blob for h in hints):
                present.add(type_id)
    return present, has_cert, rows


def legal_checklist(case_ref: str = "") -> str:
    """What must be proven for this case's charges, what the evidence already covers,
    and what is missing or inadmissible."""
    emitter = _emitter()
    with _read_session() as session, _step(emitter, "legal", "Building the element checklist") as handle:
        case = _resolve_case(session, case_ref)
        if not case:
            handle.output = "case not found"
            return f"No case found matching '{case_ref}'."
        case_id = int(case["casemasterid"])
        crime_no = str(case["crimeno"])
        handle.query = "ActSectionAssociation -> EXT_SectionMap -> EXT_LegalElement -> EXT_ElementSatisfiedBy"

        rows = _rows(session, _CHECKLIST_SQL, case_id=case_id)
        if not rows:
            handle.output = "no charges"
            return f"Case {crime_no} has no charged sections recorded, so there is nothing to check yet."

        present, has_cert, evidence_rows = _classify_evidence(session, case_id)

        # Group by element, then decide a status per element from real evidence.
        elements: dict[str, dict[str, Any]] = {}
        for r in rows:
            entry = elements.setdefault(r["element_id"], {
                "act": r["act"], "section": r["section"], "section_id": r["section_id"],
                "name": r["element"], "desc": r["element_desc"], "satisfiers": [],
            })
            if r["evidence_type_id"]:
                entry["satisfiers"].append({
                    "id": r["evidence_type_id"], "name": r["evidence_name"], "needs_63": bool(r["needs_63"]),
                })

        checklist: list[dict[str, Any]] = []
        for element_id, e in elements.items():
            have = [s for s in e["satisfiers"] if s["id"] in present]
            # Amber, not green, when the supporting evidence is electronic and its BSA
            # s63 certificate is absent: the material exists but is not admissible as-is.
            # That distinction is the entire point of the checklist.
            needs_cert = [s for s in have if s["needs_63"]]
            if not e["satisfiers"]:
                status, why = "amber", "No catalogued evidence type covers this element - prove it by narrative and corroboration."
            elif not have:
                status = "red"
                why = "Missing: " + ", ".join(s["name"] for s in e["satisfiers"][:3])
            elif needs_cert and not has_cert:
                status = "amber"
                why = (f"Present but not yet admissible: {', '.join(s['name'] for s in needs_cert)} "
                       f"require a BSA s63 certificate, which is not on file.")
            else:
                status = "green"
                why = "Covered by: " + ", ".join(s["name"] for s in have)
            checklist.append({
                "element_id": element_id, "act": e["act"], "section": e["section"],
                "section_id": e["section_id"], "name": e["name"], "status": status, "why": why,
            })

        handle.emit_artifact(TableArtifact(
            id=_aid("tbl"), title=f"Element checklist - {crime_no}",
            columns=["Status", "Charge", "Must prove", "Assessment"],
            rows=[[c["status"].upper(), f"{c['act']} {c['section']}", c["name"], c["why"]] for c in checklist],
            caption=("Green = covered by evidence on file. Amber = present but inadmissible or unsupported. "
                     "Red = missing. Decision support for the IO, not a prosecution score."),
        ))

        # Precedents that turned on an element we flagged: the "past cases failed exactly
        # here" moment. Only cite ones tied to a gap, not every precedent for the section.
        flagged = [c["element_id"] for c in checklist if c["status"] != "green"]
        precedents = _rows(session, """
            SELECT DISTINCT p.CaseName AS case_name, p.Citation AS citation, p.Court AS court,
                   p.Year AS year, p.Outcome AS outcome, p.ElementTurnedOn AS element_id,
                   p.HoldingSummary AS holding
            FROM EXT_Precedent p
            WHERE p.ElementTurnedOn = ANY(:eids) AND p.IsOverruled = 0
            ORDER BY p.Year DESC
        """, eids=flagged) if flagged else []

        for p in precedents[:4]:
            emitter and emitter.citation(AssistantCitation(
                id=_aid("cite"), label=f"{p['case_name']} {p['citation']}",
                source=f"{p['court']} ({p['year']}) - {p['outcome']}",
                snippet=(p["holding"] or "")[:280],
            ))

        counts = {s: sum(1 for c in checklist if c["status"] == s) for s in ("green", "amber", "red")}
        handle.output = f"{counts['green']} green / {counts['amber']} amber / {counts['red']} red"

        out = [
            f"LEGAL CHECKLIST for {crime_no}",
            f"  charges: {', '.join(sorted({'{} {}'.format(c['act'], c['section']) for c in checklist}))}",
            f"  evidence on file: {', '.join(sorted(present)) or 'none classifiable'}"
            f" | BSA s63 certificate: {'on file' if has_cert else 'NOT on file'}",
            f"  {counts['green']} proven / {counts['amber']} at risk / {counts['red']} missing",
            "",
        ]
        for c in checklist:
            out.append(f"  [{c['status'].upper():<5}] {c['act']} {c['section']} - {c['name']}")
            out.append(f"          {c['why']}")
        if precedents:
            out += ["", "PRECEDENTS that turned on the flagged elements (real judgments):"]
            for p in precedents[:5]:
                out.append(f"  {p['case_name']}, {p['citation']} ({p['court']}, {p['year']}) - {p['outcome']}")
                out.append(f"      {(p['holding'] or '')[:220]}")
        out += ["", "This is decision support, not a prosecution prediction. Verify section mappings with counsel."]
        return "\n".join(out)


def find_precedents(section: str = "", element: str = "", outcome: str = "") -> str:
    """Real judgments for a section or legal element, and why each was won or lost."""
    emitter = _emitter()
    with _read_session() as session, _step(emitter, "legal", "Searching precedents") as handle:
        where = ["p.IsOverruled = 0"]
        params: dict[str, Any] = {}
        if section:
            # Accept either spelling: "66D", "IT 66D", "IT_66D", "ITACT 66D".
            token = section.replace(" ", "_").upper()
            where.append("(upper(p.SectionID) LIKE :sec OR upper(p.SectionID) IN "
                         "(SELECT upper(SectionID) FROM EXT_SectionMap WHERE upper(ActCode) LIKE :sec2 OR SectionCode = :sec3))")
            params["sec"] = f"%{token}%"
            params["sec2"] = f"%{token}%"
            params["sec3"] = section.strip()
        if element:
            where.append("(upper(p.ElementTurnedOn) LIKE :el OR p.ElementTurnedOn IN "
                         "(SELECT ElementID FROM EXT_LegalElement WHERE Name ILIKE :el2))")
            params["el"] = f"%{element.replace(' ', '_').upper()}%"
            params["el2"] = f"%{element}%"
        if outcome:
            where.append("p.Outcome ILIKE :oc")
            params["oc"] = f"%{outcome}%"

        sql = f"""
            SELECT p.CaseName AS case_name, p.Citation AS citation, p.Court AS court, p.Year AS year,
                   p.Outcome AS outcome, p.SectionID AS section_id, p.ElementTurnedOn AS element_id,
                   p.HoldingSummary AS holding, le.Name AS element_name
            FROM EXT_Precedent p
            LEFT JOIN EXT_LegalElement le ON le.ElementID = p.ElementTurnedOn
            WHERE {' AND '.join(where)}
            ORDER BY p.Year DESC LIMIT 20
        """
        handle.query = " ".join(sql.split())
        rows = _rows(session, sql, **params)
        if not rows:
            handle.output = "no precedents"
            return f"No precedents found for section='{section}' element='{element}'."

        handle.emit_artifact(TableArtifact(
            id=_aid("tbl"), title="Precedents",
            columns=["Case", "Citation", "Court", "Year", "Outcome", "Turned on"],
            rows=[[r["case_name"], r["citation"], r["court"], r["year"], r["outcome"],
                   r["element_name"] or r["element_id"]] for r in rows],
            caption="Real judgments, attributed. Case data in this platform is synthetic; these are not.",
        ))
        for r in rows[:4]:
            emitter and emitter.citation(AssistantCitation(
                id=_aid("cite"), label=f"{r['case_name']} {r['citation']}",
                source=f"{r['court']} ({r['year']}) - {r['outcome']}", snippet=(r["holding"] or "")[:280],
            ))
        handle.output = f"{len(rows)} precedents"
        out = [f"PRECEDENTS ({len(rows)}):"]
        for r in rows:
            out.append(f"  {r['case_name']}, {r['citation']} ({r['court']}, {r['year']}) - {r['outcome']}")
            out.append(f"      turned on: {r['element_name'] or r['element_id']}")
            out.append(f"      {(r['holding'] or '')[:240]}")
        return "\n".join(out)


# =============================================================================
# Registry
# =============================================================================

# Descriptions are the routing logic -- the LLM picks tools from these alone, so they say
# when to use each tool, not just what it does.
_SPECS: list[tuple[Callable[..., str], str]] = [
    (get_case_summary,
     "Full context for ONE case: parties, charges, dated timeline, evidence on file, brief facts. "
     "Use this first whenever the officer names or implies a specific case. "
     "case_ref accepts a CrimeNo (18 digits), a case_id, or '' for the case in context."),
    (query_case_stats,
     "Counts and trends across cases. Use for 'how many', 'which district', 'is X rising', 'top N'. "
     "group_by: district | crime_type | month | status. Optional filters: crime_type, district, "
     "date_from/date_to (YYYY-MM-DD). For a surge, group_by='month' with a crime_type filter."),
    (run_sql_select,
     "Run a read-only SQL SELECT against Postgres for anything the other tools don't cover. "
     "Use when a question needs a join, filter or aggregate no parameterised tool offers. "
     "IMPORTANT: Transaction has NO case_id / CaseMasterID column and no FK to CaseMaster -- "
     "do not try to join them directly, it will fail every time. To find which case(s) mention "
     "an account/upi/phone/imei/ip, or which identifiers are shared across cases, use "
     "EXT_Mentions(case_master_id, object_id, object_type, observed_date) instead. "
     "object_type is PLURAL and lowercase -- exactly one of: 'accounts', 'upis', 'phones', "
     "'imeis', 'ips' (never 'account'/'upi'/singular -- that silently matches nothing and "
     "returns zero rows, which looks like 'no data found' but is actually a wrong literal). "
     "e.g. \"SELECT object_id, object_type, count(DISTINCT case_master_id) FROM EXT_Mentions "
     "GROUP BY object_id, object_type HAVING count(DISTINCT case_master_id) > 1\" finds shared "
     "identifiers directly. (find_links_between_cases does this same join for specific known cases.) "
     "Other key tables: CaseMaster(CaseMasterID, CrimeNo, CrimeRegisteredDate, BriefFacts, Latitude, "
     "Longitude, CrimeMajorHeadID, CrimeMinorHeadID), CrimeHead(CrimeHeadID, CrimeGroupName), "
     "CrimeSubHead(CrimeSubHeadID, CrimeHeadName), EXT_CaseGeo(CaseMasterID, IncidentDistrict, Pincode), "
     "Accused/Victim/ComplainantDetails(CaseMasterID, ...Name), Account(account_id, account_number_raw, "
     "bank_name, branch_district, is_flagged_mule, kyc_name, linked_case_id), "
     "Transaction(from_account_id, to_account_id, to_wallet_address, amount, txn_timestamp, mode), "
     "Evidence(case_id, doc_type, original_filename), EXT_SubEvent(CaseMasterID, Label, Timestamp), "
     "ActSectionAssociation(CaseMasterID, ActCode, SectionCode). "
     "Postgres folds identifiers to lowercase; alias columns to control result keys. Single SELECT only."),
    (trace_money_flow,
     "Follow money out of a case (case_ref) or one account (account_number), in time order, up to 6 hops. "
     "Reports total moved, elapsed time, crypto cash-out, and which funds are still FREEZABLE "
     "(arrived but never moved on). Use for 'where did the money go', 'how fast', 'what can we freeze'."),
    (find_links_between_cases,
     "Given 2+ case refs, find the accounts/UPIs/devices/phones/IPs they SHARE. "
     "This is the 'are these separate cases actually one network?' move. "
     "Run it after find_similar_cases to turn a meaning-match into a structural link."),
    (expand_entity,
     "Show what one identifier (account number, UPI, IMEI, phone, IP) connects to, 1-3 hops out. "
     "Use to pivot from a single identifier into its network."),
    (person_history,
     "All cases tied to a person AND the aliases that resolve to them via shared device/UPI/phone. "
     "Use for 'do we know this accused', 'is he a repeat offender', 'show his history/escalation'."),
    (detect_community,
     "Cluster cases that share infrastructure and rank the most central objects: "
     "'is this an organised ring or copycats?'. Pass case_refs, or filter by crime_type and days "
     "(e.g. days=21) to analyse a recent surge."),
    (run_cypher_read,
     "Run a read-only Cypher query for graph questions the other tools don't cover. "
     "Labels: CaseMaster{case_id, display_name(=CrimeNo)}, Accused, Victim, ComplainantDetails, "
     "Account, UPIHandle, Device, PhoneNumber, IP, Wallet, InvestigationReport -- all keyed by entity_uid, "
     "with origin='historical'|'demo' and display_name. "
     "Relationships: (CaseMaster)-[:MENTIONS]->(object), (person)-[:INVOLVES]->(CaseMaster), "
     "(person)-[:OWNS]->(object), (Account)-[:TRANSACTED_WITH {amount, txn_timestamp, mode}]->(Account|Wallet), "
     "(CaseMaster)-[:HAS_EVIDENCE]->(InvestigationReport). No GDS/APOC. Single read query only."),
    (find_similar_cases,
     "Find cases with the same modus operandi by MEANING, not keywords -- the cross-district "
     "'same script' match. Pass case_ref to match an existing case, or text_query to describe an MO. "
     "Returns case refs you should then pass to find_links_between_cases."),
    (legal_checklist,
     "For one case: what each charged section requires you to prove, whether the evidence on file "
     "covers it (green/amber/red), and real precedents that turned on the flagged elements. "
     "Amber means present but inadmissible -- typically electronic evidence with no BSA s63 certificate. "
     "Use for 'is this prosecutable', 'what am I missing', 'what must I prove'."),
    (find_precedents,
     "Real judgments for a section (e.g. '66D', 'BNS 318', 'PMLA 3') or a legal element, "
     "and why each was won or lost. Filter by outcome ('acquittal'/'conviction')."),
]

# agent_kind per tool: the UI renders each step under its specialist's label, and it's
# how the reasoning trail shows which "agent" did what.
AGENT_BY_TOOL: dict[str, str] = {
    "get_case_summary": "sql", "query_case_stats": "sql", "run_sql_select": "sql",
    "trace_money_flow": "graph", "find_links_between_cases": "graph", "expand_entity": "graph",
    "person_history": "graph", "detect_community": "graph", "run_cypher_read": "graph",
    "find_similar_cases": "vector",
    "legal_checklist": "legal", "find_precedents": "legal",
}


def build_tools(
    extra: list[StructuredTool] | None = None,
    tool_names: set[str] | None = None,
) -> list[StructuredTool]:
    """All specialist tools, each blocking body pushed onto a worker thread.

    Both func and coroutine are supplied: the arg schema is inferred from the plain
    function's signature (the _in_thread wrapper is **kwargs, which infers nothing), while
    the agent's async path calls the coroutine and keeps the blocking work off the loop.
    """
    tools = [
        StructuredTool.from_function(
            func=fn, coroutine=_in_thread(fn), name=fn.__name__,
            description=description, parse_docstring=False,
        )
        for fn, description in _SPECS
        if tool_names is None or fn.__name__ in tool_names
    ]
    return tools + list(extra or [])

