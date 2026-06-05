"""Small async event bus used by the extracted OAuth runtime."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any


class Events(StrEnum):
    OAUTH_THROTTLED = "oauth.token.throttled"
    OAUTH_TOKEN_ROTATED = "oauth.token.rotated"
    OAUTH_EXHAUSTED = "oauth.pool.exhausted"
    OAUTH_FALLBACK_REQUESTED = "oauth.fallback.requested"
    OAUTH_FALLBACK_GRANTED = "oauth.fallback.granted"
    OAUTH_FALLBACK_DENIED = "oauth.fallback.denied"


Handler = Callable[..., Any | Awaitable[Any]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[Events, list[Handler]] = {}

    def on(self, event: Events, handler: Handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    async def emit(self, event: Events, **payload: Any) -> None:
        for handler in self._handlers.get(event, []):
            result = handler(**payload)
            if inspect.isawaitable(result):
                await result


event_bus = EventBus()
