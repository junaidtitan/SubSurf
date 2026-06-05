"""Throttle signaling and API-key fallback gate for SubSurf.

The IPC surface is file-based:

1. VM/process writes `throttled.flag` when OAuth auth/rate/usage limits hit.
2. Host watcher rotates the token or marks the pool exhausted.
3. If fallback is allowed, host writes `fallback_grant.json` and the process
   can fall through to API-key billing.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


class RateLimitExhausted(Exception):
    """Raised when a rate-limit retry budget is exhausted."""

    def __init__(self, message: str, *, attempts: int = 0):
        super().__init__(message)
        self.attempts = attempts


@dataclass(frozen=True)
class ThrottleSignal:
    """A rate-limit, usage-limit, or auth condition on the OAuth path."""

    kind: str  # "rate_limit" | "usage_limit" | "auth" | "unknown"
    retry_after_s: float | None
    message: str

    @property
    def is_rotatable(self) -> bool:
        return self.kind in {"rate_limit", "usage_limit", "auth"}


def classify_oauth_error(exc: BaseException) -> ThrottleSignal | None:
    """Return a throttle signal for Anthropic OAuth account-health failures."""
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return None

    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None) or {}
    msg = str(exc)

    if isinstance(exc, anthropic.RateLimitError):
        retry_after = retry_after_seconds(exc)
        if looks_like_usage_limit(msg, body):
            return ThrottleSignal("usage_limit", retry_after, msg[:500])
        return ThrottleSignal("rate_limit", retry_after, msg[:500])

    if isinstance(exc, anthropic.AuthenticationError):
        return ThrottleSignal("auth", None, msg[:500])

    if status == 403 and looks_like_account_suspended(msg, body):
        return ThrottleSignal("usage_limit", None, msg[:500])

    return None


def retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        value = response.headers.get("retry-after")
    except AttributeError:
        return None
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def looks_like_usage_limit(msg: str, body: Any) -> bool:
    markers = ("usage limit", "quota", "monthly limit", "subscription")
    hay = (msg + " " + json.dumps(body, default=str)).lower()
    return any(marker in hay for marker in markers)


def looks_like_account_suspended(msg: str, body: Any) -> bool:
    markers = ("suspended", "disabled", "banned")
    hay = (msg + " " + json.dumps(body, default=str)).lower()
    return any(marker in hay for marker in markers)


def write_throttle_flag(path: str | Path, signal: ThrottleSignal) -> None:
    """Record a throttle event for the host-side watcher."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": signal.kind,
        "retry_after_s": signal.retry_after_s,
        "message": signal.message,
        "detected_at": time.time(),
        "hostname": os.uname().nodename,
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(p)
    log.warning("oauth_throttle_flag_written", path=str(p), kind=signal.kind)


def read_throttle_flag(path: str | Path) -> dict[str, Any] | None:
    p = Path(path).expanduser()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def clear_throttle_flag(path: str | Path) -> None:
    p = Path(path).expanduser()
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def request_api_key_fallback(
    request_path: str | Path,
    reason: str,
    vm_id: str | None = None,
) -> None:
    """Ask the host for permission to use API-key fallback."""
    p = Path(request_path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "requested_at": time.time(),
        "vm_id": vm_id or os.uname().nodename,
        "reason": reason,
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(p)
    log.warning("oauth_fallback_requested", path=str(p), reason=reason)


def check_api_key_fallback_grant(grant_path: str | Path) -> dict[str, Any] | None:
    """Return an active fallback grant, if one exists."""
    p = Path(grant_path).expanduser()
    if not p.exists():
        return None
    try:
        grant = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    now = time.time()
    expires_at = grant.get("expires_at")
    if expires_at is not None and now > expires_at:
        log.info("oauth_fallback_grant_expired", grant_path=str(p))
        return None

    uses_remaining = grant.get("uses_remaining")
    if uses_remaining is not None and uses_remaining <= 0:
        return None

    return grant


def consume_fallback_grant(grant_path: str | Path) -> None:
    """Decrement a fallback grant's remaining use count."""
    p = Path(grant_path).expanduser()
    if not p.exists():
        return
    try:
        grant = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return
    uses = grant.get("uses_remaining")
    if uses is None:
        return
    grant["uses_remaining"] = max(0, uses - 1)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(grant, indent=2))
    tmp.replace(p)
