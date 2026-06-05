"""Anthropic OAuth client for Claude Code subscription tokens.

This bypasses LiteLLM and talks to api.anthropic.com directly with bearer
auth (`auth_token=` in the Anthropic SDK). The token file is owned by the
host-side bridge/pool tooling; this module only reads it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
import structlog

from subsurf.models import (
    resolve_model_id,
    strip_provider_prefix as strip_model_provider_prefix,
    supports_sampling,
)

log = structlog.get_logger(__name__)


# Claude Code request identity. Disable with SUBSURF_OAUTH_SPOOF=0.
_CC_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
_CC_BETA = "oauth-2025-04-20,claude-code-20250219"
_CC_UA = "claude-cli/2.1.81 (external, cli)"
_SPOOF_ENV = os.environ.get("SUBSURF_OAUTH_SPOOF", os.environ.get("PILOT_OAUTH_SPOOF", "1"))
_SPOOF_ON = _SPOOF_ENV.lower() not in {"0", "false", ""}
_CC_HEADERS = {"anthropic-beta": _CC_BETA, "User-Agent": _CC_UA} if _SPOOF_ON else {}


def _with_cc_identity(system_prompt: str | None) -> Any:
    """Return a system value whose first block is the Claude Code identity."""
    if not _SPOOF_ON:
        return system_prompt
    blocks: list[dict[str, str]] = [{"type": "text", "text": _CC_IDENTITY}]
    if system_prompt:
        blocks.append({"type": "text", "text": system_prompt})
    return blocks


@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class Message:
    content: str


@dataclass
class Choice:
    message: Message


@dataclass
class Response:
    choices: list[Choice]
    usage: Usage


class OAuthTokenMissing(RuntimeError):
    """Raised when the token file does not exist or is empty."""


def load_oauth_token(path: str | Path) -> str:
    """Read the current OAuth access token from disk."""
    p = Path(path).expanduser()
    if not p.exists():
        raise OAuthTokenMissing(
            f"OAuth token not found at {p}. Run `subsurf-setup` or "
            "`subsurf-wizard` to provision it.",
        )
    token = p.read_text().strip()
    if not token:
        raise OAuthTokenMissing(f"OAuth token file {p} is empty.")
    return token


class AnthropicOAuthClient:
    """Thin async wrapper around the Anthropic SDK using bearer auth."""

    def __init__(self, token_path: str | Path) -> None:
        self._token_path = token_path
        self._cached_token: str | None = None
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self, *, force_reload: bool = False) -> anthropic.AsyncAnthropic:
        token = load_oauth_token(self._token_path)
        if force_reload or self._client is None or token != self._cached_token:
            self._client = anthropic.AsyncAnthropic(
                auth_token=token,
                default_headers=_CC_HEADERS or None,
            )
            self._cached_token = token
            log.debug("oauth_client_initialized")
        return self._client

    def reload_token(self) -> None:
        """Force a re-read of the token file on the next call."""
        self._cached_token = None
        self._client = None

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **extra: Any,
    ) -> Response:
        client = self._get_client()
        system_prompt, converted = split_system_and_convert(messages)
        if not converted:
            raise ValueError(
                "no user/assistant messages to send; Anthropic requires at "
                "least one non-system message",
            )

        kwargs = build_message_create_kwargs(
            messages=converted,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            extra=extra,
        )
        response = await client.messages.create(**kwargs)
        text_parts = [
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        ]
        return Response(
            choices=[Choice(message=Message(content="".join(text_parts)))],
            usage=Usage(
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
            ),
        )


def strip_provider_prefix(model: str) -> str:
    """`anthropic_oauth/claude-sonnet-4-6` -> `claude-sonnet-4-6`."""
    return strip_model_provider_prefix(model)


def build_message_create_kwargs(
    *,
    messages: list[dict[str, Any]],
    model: str,
    temperature: float | None,
    max_tokens: int,
    system_prompt: str | None,
    extra: dict[str, Any],
) -> dict[str, Any]:
    """Build Anthropic Messages kwargs with model-aware compatibility rules."""
    resolved_model = resolve_model_id(model)
    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None and supports_sampling(resolved_model):
        kwargs["temperature"] = temperature

    system_value = _with_cc_identity(system_prompt)
    if system_value is not None:
        kwargs["system"] = system_value
    if "thinking" in extra:
        kwargs["thinking"] = extra["thinking"]
    if "effort" in extra:
        kwargs["effort"] = extra["effort"]
    return kwargs


def split_system_and_convert(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Extract system prompt and convert OpenAI-style image parts."""
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        system_parts.append(part.get("text", ""))
            continue

        if role not in {"user", "assistant"}:
            raise ValueError(
                f"unsupported message role {role!r} "
                "(expected 'system' | 'user' | 'assistant')",
            )
        if content is None:
            raise ValueError(f"message with role={role!r} has null content")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            new_parts: list[dict[str, Any]] = []
            for part in content:
                if not isinstance(part, dict):
                    raise ValueError(
                        f"content part must be a dict, got {type(part).__name__}",
                    )
                ptype = part.get("type")
                if ptype == "text":
                    new_parts.append({"type": "text", "text": part.get("text", "")})
                elif ptype == "image_url":
                    new_parts.append(convert_image_url(part["image_url"]))
                elif ptype == "image":
                    new_parts.append(part)
                else:
                    raise ValueError(
                        f"unsupported content part type {ptype!r} "
                        "(expected 'text' | 'image_url' | 'image')",
                    )
            out.append({"role": role, "content": new_parts})
            continue

        raise TypeError(
            f"message content must be str or list, got {type(content).__name__}",
        )

    system_prompt = "\n\n".join(p for p in system_parts if p) or None
    return system_prompt, out


def convert_image_url(image_url: Any) -> dict[str, Any]:
    """Convert a data: image URL into Anthropic's native image block."""
    url = image_url if isinstance(image_url, str) else image_url.get("url", "")
    if not url.startswith("data:"):
        raise ValueError(
            f"OAuth client only supports data: image URLs (got {url[:40]!r}).",
        )
    header, _, b64 = url.partition(",")
    media_type = header.split(";")[0].removeprefix("data:") or "image/jpeg"
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": b64},
    }


def build_from_settings() -> AnthropicOAuthClient:
    from subsurf.config import get_settings

    return AnthropicOAuthClient(token_path=os.path.expanduser(get_settings().oauth_token_path))
