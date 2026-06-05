from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from subsurf.anthropic_oauth import Choice, Message, Response, Usage
from subsurf.config import SubSurfSettings
from subsurf.engine import SubSurfEngine, rewrite_oauth_to_litellm


def test_rewrite_oauth_to_litellm():
    assert rewrite_oauth_to_litellm("anthropic_oauth/claude-sonnet-4-6") == (
        "anthropic/claude-sonnet-4-6"
    )


@pytest.fixture
def settings(tmp_path: Path) -> SubSurfSettings:
    return SubSurfSettings(
        oauth_token_path=str(tmp_path / "oauth_token"),
        oauth_throttle_flag_path=str(tmp_path / "throttled.flag"),
        oauth_fallback_request_path=str(tmp_path / "fallback_request.json"),
        oauth_fallback_grant_path=str(tmp_path / "fallback_grant.json"),
    )


@pytest.mark.asyncio
async def test_oauth_success(settings: SubSurfSettings, monkeypatch):
    engine = SubSurfEngine(settings=settings)
    client = MagicMock()
    client.complete = AsyncMock(return_value=fake_response("hello"))
    client.reload_token = MagicMock()
    monkeypatch.setattr(engine, "_get_oauth_client", lambda: client)

    result = await engine.complete([{"role": "user", "content": "hi"}])
    assert result == "hello"
    assert client.complete.await_count == 1


@pytest.mark.asyncio
async def test_pool_exhausted_without_grant_writes_request(settings: SubSurfSettings):
    engine = SubSurfEngine(settings=settings)
    signal = MagicMock(kind="usage_limit", message="usage limit reached")
    with pytest.raises(RuntimeError, match="OAuth pool exhausted"):
        await engine._handle_pool_exhausted(signal)

    request = json.loads(Path(settings.oauth_fallback_request_path).read_text())
    assert "usage_limit" in request["reason"]


@pytest.mark.asyncio
async def test_pool_exhausted_with_grant_falls_through(settings: SubSurfSettings, monkeypatch):
    settings.oauth_allow_api_key_fallback = True
    Path(settings.oauth_fallback_grant_path).write_text(json.dumps({
        "granted_at": time.time(),
        "expires_at": time.time() + 600,
        "max_uses": 5,
        "uses_remaining": 5,
    }))
    engine = SubSurfEngine(settings=settings)
    signal = MagicMock(kind="usage_limit", message="usage limit reached")
    with pytest.raises(Exception, match="grant-honored"):
        await engine._handle_pool_exhausted(signal)

    grant = json.loads(Path(settings.oauth_fallback_grant_path).read_text())
    assert grant["uses_remaining"] == 4


def fake_response(text: str) -> Response:
    return Response(
        choices=[Choice(message=Message(content=text))],
        usage=Usage(prompt_tokens=10, completion_tokens=20),
    )
