"""Per-run event fan-out with replay.

Same in-process pub/sub shape as services/pipeline_broadcast.py, plus a replay buffer,
which this needs and that one doesn't: the frontend POSTs /assistant/message and only
then opens the WebSocket (assistantClient.ts), so the agent is already emitting steps
before anyone is listening. Without replay the first steps -- often the whole answer for
a fast run -- are lost, and the UI sits blank.

ponytail: single-process only, same ceiling as pipeline_broadcast. Fine because AppSail
runs one instance; a second replica would need Redis pub/sub or sticky routing.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# run_id -> every event emitted so far, in order.
_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
# run_id -> live subscriber queues.
_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
# run_id -> monotonic time the run reached a terminal event.
_finished_at: dict[str, float] = {}

# How long a finished run's history stays replayable. Covers a WS reconnect or a slow
# client attaching after the run already completed.
RETENTION_SECONDS = 900.0


def publish(run_id: str, event: dict[str, Any]) -> None:
    """Append to history and fan out to live subscribers."""
    _history[run_id].append(event)
    if event.get("type") in ("done", "error"):
        _finished_at[run_id] = time.monotonic()
        _sweep()

    for queue in list(_subscribers.get(run_id, ())):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:  # pragma: no cover - unbounded queues today
            logger.warning("assistant bus: dropping event for run_id=%s, queue full", run_id)


def subscribe(run_id: str) -> tuple[asyncio.Queue, list[dict[str, Any]]]:
    """Returns (live queue, everything already emitted).

    The caller must send the replay before draining the queue, and both come from this
    one call so no event can slip between the two -- publish() appends to history and
    fans out synchronously, and there's no await here, so nothing interleaves.
    """
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[run_id].add(queue)
    return queue, list(_history.get(run_id, ()))


def unsubscribe(run_id: str, queue: asyncio.Queue) -> None:
    subscribers = _subscribers.get(run_id)
    if not subscribers:
        return
    subscribers.discard(queue)
    if not subscribers:
        _subscribers.pop(run_id, None)


def is_finished(run_id: str) -> bool:
    return run_id in _finished_at


def history(run_id: str) -> list[dict[str, Any]]:
    """Everything emitted for a run so far. Used to persist the turn and to let the
    report skill pull in artifacts the analysis tools already produced."""
    return list(_history.get(run_id, ()))


def artifacts_of(run_id: str) -> list[dict[str, Any]]:
    return [e["artifact"] for e in _history.get(run_id, ()) if e.get("type") == "artifact"]


def citations_of(run_id: str) -> list[dict[str, Any]]:
    return [e["citation"] for e in _history.get(run_id, ()) if e.get("type") == "citation"]


def context_inventory(run_id: str) -> str:
    """Compact block listing artifacts + citations so specialists can refer back to them."""
    arts = artifacts_of(run_id)
    cites = citations_of(run_id)
    if not arts and not cites:
        return ""
    lines: list[str] = []
    if arts:
        lines.append("Artifacts generated so far this turn (id / title / format / url):")
        for a in arts:
            lines.append(
                f"- {a.get('id')}: {a.get('title')!r} [{a.get('format') or a.get('kind')}] "
                f"{a.get('url') or ''}"
            )
    if cites:
        # No raw cite-id here: the model was echoing "[cite-abc123] ... (CaseMaster.BriefFacts)"
        # verbatim into the answer. It doesn't need the internal id — the citation panel
        # renders the sources; the model just needs to know what's already cited.
        lines.append("Sources already cited (do not repeat these ids or column names in prose):")
        for c in cites[:12]:
            lines.append(f"- {c.get('label')}")
    return "\n".join(lines)


def _sweep() -> None:
    """Drop history for runs that finished over RETENTION_SECONDS ago.

    Called on terminal events only -- history has to outlive the run itself (that's the
    point of replay), so it can't be freed when the last subscriber leaves, and without
    a sweep a long-lived process would hold every event of every run forever.
    """
    cutoff = time.monotonic() - RETENTION_SECONDS
    stale = [run_id for run_id, at in _finished_at.items() if at < cutoff]
    for run_id in stale:
        _history.pop(run_id, None)
        _finished_at.pop(run_id, None)
        _subscribers.pop(run_id, None)
    if stale:
        logger.debug("assistant bus: swept %d finished run(s)", len(stale))
