"""In-process fan-out from the Signals webhook (POST /internal/pipeline-event) to
WebSocket subscribers (GET /ws/pipeline/{run_id}). Postgres is still the source of
truth; this is only a push-first shortcut so the WS doesn't have to wait a full
poll interval to see a stage change.

ponytail ceiling: subscribers/dedupe state live in one process's memory, so a
webhook delivery landing on a different backend instance than the WS client won't
push directly. Fine for the single-instance demo; the WS's own Postgres poll
fallback covers that case. Upgrade path: Redis pub/sub for cross-instance fan-out.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
_seen_event_ids: set[str] = set()
logger = logging.getLogger(__name__)


def subscribe(run_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[run_id].add(queue)
    logger.debug("pipeline_broadcast subscribe run_id=%s subscribers=%d", run_id, len(_subscribers[run_id]))
    return queue


def unsubscribe(run_id: str, queue: asyncio.Queue) -> None:
    _subscribers[run_id].discard(queue)
    if not _subscribers[run_id]:
        _subscribers.pop(run_id, None)
        logger.debug("pipeline_broadcast unsubscribe run_id=%s subscribers=0", run_id)
        return
    logger.debug("pipeline_broadcast unsubscribe run_id=%s subscribers=%d", run_id, len(_subscribers[run_id]))


def publish(run_id: str, event: dict) -> None:
    for queue in list(_subscribers.get(run_id, ())):
        try:
            queue.put_nowait(event)
        except Exception:
            logger.exception("pipeline_broadcast publish failed run_id=%s", run_id)
    logger.debug("pipeline_broadcast publish run_id=%s fanout=%d", run_id, len(_subscribers.get(run_id, ())))


def is_duplicate_event(event_id: str) -> bool:
    """Marks event_id as seen; returns True if it was already delivered."""
    if not event_id:
        return False
    if event_id in _seen_event_ids:
        logger.debug("pipeline_broadcast duplicate event_id=%s", event_id)
        return True
    _seen_event_ids.add(event_id)
    return False
