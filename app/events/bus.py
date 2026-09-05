"""Event bus: publish to Redis, fan out to WebSocket clients in this process.

Every event is a JSON frame:
    {"type": "clash.opened", "project_id": "...", "ts": "...", "data": {...}}

Publishing goes through Redis so that multiple API processes all see every
event. One background subscriber per process (psubscribe on the project
channel pattern) delivers frames to the local WebSocket connections that
registered for that project.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings

log = logging.getLogger(__name__)

EVENT_TYPES = (
    "claim.created",
    "claim.retired",
    "clash.opened",
    "clash.resolved",
    "memory.written",
    "memory.read",
    "handoff.filed",
    "pr.opened",
)

CHANNEL_PREFIX = "consensus:events:"


def _channel(project_id: uuid.UUID | str) -> str:
    return f"{CHANNEL_PREFIX}{project_id}"


def _json_default(o: Any) -> Any:
    if isinstance(o, uuid.UUID):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"not serialisable: {type(o)!r}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=_json_default)


class EventBus:
    def __init__(self, redis_url: str | None = None) -> None:
        self._url = redis_url or get_settings().redis_url
        self._redis: aioredis.Redis | None = None
        self._subscribers: dict[str, set[asyncio.Queue[str]]] = defaultdict(set)
        self._listener: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # -- lifecycle -----------------------------------------------------------

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._url, decode_responses=True)
        return self._redis

    async def start(self) -> None:
        if self._listener is None:
            self._listener = asyncio.create_task(self._listen(), name="event-bus-listener")

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._listener
            self._listener = None
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.aclose()
            self._redis = None

    # -- publish -------------------------------------------------------------

    def make_frame(self, project_id: uuid.UUID | str, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "type": type_,
            "project_id": str(project_id),
            "ts": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }

    async def publish(self, project_id: uuid.UUID | str, type_: str, data: dict[str, Any]) -> None:
        if type_ not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type_}")
        frame = self.make_frame(project_id, type_, data)
        payload = dumps(frame)
        try:
            await self.redis.publish(_channel(project_id), payload)
        except Exception:  # Redis down must not break the declare flow
            log.exception("event publish failed; delivering locally only")
            self._deliver_local(str(project_id), payload)

    # -- subscribe -----------------------------------------------------------

    def subscribe(self, project_id: uuid.UUID | str) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self._subscribers[str(project_id)].add(q)
        return q

    def unsubscribe(self, project_id: uuid.UUID | str, q: asyncio.Queue[str]) -> None:
        self._subscribers[str(project_id)].discard(q)

    def _deliver_local(self, project_id: str, payload: str) -> None:
        for q in list(self._subscribers.get(project_id, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                log.warning("dropping event for slow websocket client")

    async def _listen(self) -> None:
        while True:
            try:
                pubsub = self.redis.pubsub()
                await pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
                async for msg in pubsub.listen():
                    if msg.get("type") != "pmessage":
                        continue
                    channel = msg["channel"]
                    project_id = channel[len(CHANNEL_PREFIX):]
                    self._deliver_local(project_id, msg["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("event bus listener error; reconnecting in 1s")
                await asyncio.sleep(1)

    # -- waiting on a specific event -------------------------------------------

    async def wait_for(
        self,
        project_id: uuid.UUID | str,
        predicate,
        timeout: float,
    ) -> dict[str, Any] | None:
        """Block until an event for the project satisfies `predicate`, or timeout."""
        q = self.subscribe(project_id)
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return None
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    return None
                frame = json.loads(payload)
                if predicate(frame):
                    return frame
        finally:
            self.unsubscribe(project_id, q)


_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def set_bus(bus: EventBus | None) -> None:
    global _bus
    _bus = bus
