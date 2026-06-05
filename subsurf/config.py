"""Runtime settings for SubSurf.

Settings are intentionally environment-only to keep the extracted project
independent from Pilot's Pydantic configuration stack.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off", ""}


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value)


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    return float(value)


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value


@dataclass
class SubSurfSettings:
    """Configuration consumed by the OAuth client and small runtime engine."""

    reasoning_model: str = "claude-sonnet-4-6"
    oauth_token_path: str = "~/.config/subsurf/oauth_token"
    oauth_throttle_flag_path: str = "~/.config/subsurf/throttled.flag"
    oauth_fallback_request_path: str = "~/.config/subsurf/fallback_request.json"
    oauth_fallback_grant_path: str = "~/.config/subsurf/fallback_grant.json"
    oauth_allow_api_key_fallback: bool = False
    max_tokens: int = 8192
    temperature: float = 0.0
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8765
    gateway_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "SubSurfSettings":
        return cls(
            reasoning_model=os.environ.get("SUBSURF_REASONING_MODEL", cls.reasoning_model),
            oauth_token_path=os.environ.get("SUBSURF_OAUTH_TOKEN_PATH", cls.oauth_token_path),
            oauth_throttle_flag_path=os.environ.get(
                "SUBSURF_OAUTH_THROTTLE_FLAG_PATH",
                cls.oauth_throttle_flag_path,
            ),
            oauth_fallback_request_path=os.environ.get(
                "SUBSURF_OAUTH_FALLBACK_REQUEST_PATH",
                cls.oauth_fallback_request_path,
            ),
            oauth_fallback_grant_path=os.environ.get(
                "SUBSURF_OAUTH_FALLBACK_GRANT_PATH",
                cls.oauth_fallback_grant_path,
            ),
            oauth_allow_api_key_fallback=_bool_env(
                "SUBSURF_OAUTH_ALLOW_API_KEY_FALLBACK",
                cls.oauth_allow_api_key_fallback,
            ),
            max_tokens=_int_env("SUBSURF_MAX_TOKENS", cls.max_tokens),
            temperature=_float_env("SUBSURF_TEMPERATURE", cls.temperature),
            gateway_host=os.environ.get("SUBSURF_GATEWAY_HOST", cls.gateway_host),
            gateway_port=_int_env("SUBSURF_GATEWAY_PORT", cls.gateway_port),
            gateway_api_key=_optional_env("SUBSURF_GATEWAY_API_KEY"),
        )


@lru_cache
def get_settings() -> SubSurfSettings:
    return SubSurfSettings.from_env()
