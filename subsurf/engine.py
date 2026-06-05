"""Small runtime wrapper for the SubSurf OAuth client.

This is not a full agent LLM engine. It is the extracted routing behavior:
OAuth bearer call first, throttle signaling/retry, then optional API-key
fallback when the host has granted it.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

from subsurf.config import SubSurfSettings, get_settings

log = structlog.get_logger(__name__)


class OAuthFallthrough(Exception):
    """Internal signal: OAuth exhausted and API-key fallback is approved."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def rewrite_oauth_to_litellm(model: str) -> str:
    """`anthropic_oauth/claude-sonnet-4-6` -> `anthropic/claude-sonnet-4-6`."""
    if model.startswith("anthropic_oauth/"):
        return "anthropic/" + model.split("/", 1)[1]
    return model


def with_oauth_prefix(model: str) -> str:
    if model.startswith("anthropic_oauth/"):
        return model
    return f"anthropic_oauth/{model}"


class SubSurfEngine:
    """OAuth-first completion helper."""

    def __init__(self, settings: SubSurfSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._oauth_client: Any | None = None

    def _get_oauth_client(self) -> Any:
        if self._oauth_client is None:
            from subsurf.anthropic_oauth import AnthropicOAuthClient

            self._oauth_client = AnthropicOAuthClient(
                token_path=os.path.expanduser(self.settings.oauth_token_path),
            )
        return self._oauth_client

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        **extra: Any,
    ) -> str:
        model = with_oauth_prefix(model or self.settings.reasoning_model)
        temperature = self.settings.temperature if temperature is None else temperature
        try:
            return await self._oauth_call(messages, model, temperature, **extra)
        except OAuthFallthrough as fallthrough:
            log.warning("oauth_fallthrough_to_api_key", reason=fallthrough.reason)
            return await self._litellm_call(
                messages,
                rewrite_oauth_to_litellm(model),
                temperature,
                **extra,
            )

    async def _oauth_call(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        **extra: Any,
    ) -> str:
        from subsurf import throttle
        from subsurf.events import Events, event_bus

        client = self._get_oauth_client()
        max_tokens = self._max_tokens(extra)

        try:
            response = await client.complete(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **extra,
            )
        except Exception as exc:
            signal = throttle.classify_oauth_error(exc)
            if signal is None:
                raise

            throttle.write_throttle_flag(self.settings.oauth_throttle_flag_path, signal)
            await event_bus.emit(
                Events.OAUTH_THROTTLED,
                kind=signal.kind,
                retry_after_s=signal.retry_after_s,
                message=signal.message,
            )

            if signal.kind == "rate_limit":
                response = None
                for attempt in range(4):
                    delay = signal.retry_after_s or min(5 * 2**attempt, 30)
                    log.warning(
                        "oauth_rate_limit_backoff",
                        attempt=attempt + 1,
                        delay_s=round(delay, 1),
                    )
                    await asyncio.sleep(delay)
                    try:
                        response = await client.complete(
                            messages=messages,
                            model=model,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            **extra,
                        )
                        throttle.clear_throttle_flag(self.settings.oauth_throttle_flag_path)
                        break
                    except Exception as retry_exc:
                        retry_signal = throttle.classify_oauth_error(retry_exc)
                        if retry_signal is None:
                            raise
                        signal = retry_signal
                        if retry_signal.kind != "rate_limit":
                            response = None
                            break
                if response is None:
                    await self._handle_pool_exhausted(signal)
            elif signal.is_rotatable:
                client.reload_token()
                try:
                    response = await client.complete(
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **extra,
                    )
                    throttle.clear_throttle_flag(self.settings.oauth_throttle_flag_path)
                    await event_bus.emit(Events.OAUTH_TOKEN_ROTATED)
                except Exception as retry_exc:
                    retry_signal = throttle.classify_oauth_error(retry_exc)
                    if retry_signal is None:
                        raise
                    await self._handle_pool_exhausted(retry_signal)
            else:
                raise

        return response.choices[0].message.content

    async def _handle_pool_exhausted(self, signal: Any) -> None:
        from subsurf import throttle
        from subsurf.events import Events, event_bus

        await event_bus.emit(
            Events.OAUTH_EXHAUSTED,
            kind=signal.kind,
            message=signal.message,
        )

        if not self.settings.oauth_allow_api_key_fallback:
            throttle.request_api_key_fallback(
                self.settings.oauth_fallback_request_path,
                reason=f"{signal.kind}: {signal.message[:200]}",
            )
            await event_bus.emit(Events.OAUTH_FALLBACK_REQUESTED, reason=signal.message)
            raise RuntimeError(
                f"OAuth pool exhausted ({signal.kind}) and API-key fallback "
                "is not permitted.",
            )

        grant = throttle.check_api_key_fallback_grant(
            self.settings.oauth_fallback_grant_path,
        )
        if grant is None:
            throttle.request_api_key_fallback(
                self.settings.oauth_fallback_request_path,
                reason=f"{signal.kind}: {signal.message[:200]}",
            )
            await event_bus.emit(Events.OAUTH_FALLBACK_REQUESTED, reason=signal.message)
            raise RuntimeError(
                f"OAuth pool exhausted ({signal.kind}); awaiting fallback grant.",
            )

        throttle.consume_fallback_grant(self.settings.oauth_fallback_grant_path)
        await event_bus.emit(Events.OAUTH_FALLBACK_GRANTED, note=grant.get("note"))
        raise OAuthFallthrough(reason=f"grant-honored:{signal.kind}")

    async def _litellm_call(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        **extra: Any,
    ) -> str:
        import litellm

        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=self._max_tokens(extra),
            **extra,
        )
        return response.choices[0].message.content

    def _max_tokens(self, extra: dict[str, Any]) -> int:
        max_tokens = self.settings.max_tokens
        if "thinking" in extra:
            thinking = extra["thinking"]
            if thinking.get("type") == "adaptive":
                max_tokens = max(max_tokens, 16000)
            else:
                budget = thinking.get("budget_tokens", 0)
                if max_tokens <= budget:
                    max_tokens = budget + 8192
        return max_tokens
