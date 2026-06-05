from __future__ import annotations

from pathlib import Path

import pytest

from subsurf.anthropic_oauth import (
    AnthropicOAuthClient,
    OAuthTokenMissing,
    build_message_create_kwargs,
    load_oauth_token,
    split_system_and_convert,
    strip_provider_prefix,
)


def test_load_oauth_token(tmp_path: Path):
    path = tmp_path / "oauth_token"
    path.write_text("sk-ant-oat01-test\n")
    assert load_oauth_token(path) == "sk-ant-oat01-test"


def test_load_oauth_token_missing(tmp_path: Path):
    with pytest.raises(OAuthTokenMissing):
        load_oauth_token(tmp_path / "missing")


def test_strip_provider_prefix():
    assert strip_provider_prefix("anthropic_oauth/claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert strip_provider_prefix("claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_build_kwargs_resolves_alias_and_keeps_supported_temperature():
    kwargs = build_message_create_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        model="sonnet",
        temperature=0.2,
        max_tokens=100,
        system_prompt=None,
        extra={},
    )
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["temperature"] == 0.2


def test_build_kwargs_omits_temperature_for_opus_4_7_and_later():
    kwargs = build_message_create_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        model="opus",
        temperature=0.2,
        max_tokens=100,
        system_prompt=None,
        extra={},
    )
    assert kwargs["model"] == "claude-opus-4-8"
    assert "temperature" not in kwargs


def test_build_kwargs_passes_effort_and_thinking():
    kwargs = build_message_create_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        model="sonnet",
        temperature=None,
        max_tokens=100,
        system_prompt=None,
        extra={
            "effort": "high",
            "thinking": {"type": "adaptive"},
        },
    )
    assert kwargs["effort"] == "high"
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert "temperature" not in kwargs


def test_split_system_and_convert():
    system, messages = split_system_and_convert([
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hello"},
    ])
    assert system == "system prompt"
    assert messages == [{"role": "user", "content": "hello"}]


def test_rejects_unknown_role():
    with pytest.raises(ValueError, match="unsupported message role"):
        split_system_and_convert([{"role": "tool", "content": "x"}])


def test_rejects_null_content():
    with pytest.raises(ValueError, match="null content"):
        split_system_and_convert([{"role": "user", "content": None}])


@pytest.mark.asyncio
async def test_rejects_empty_payload_before_network(tmp_path: Path):
    token = tmp_path / "oauth_token"
    token.write_text("sk-ant-oat01-test")
    client = AnthropicOAuthClient(token_path=token)
    with pytest.raises(ValueError, match="at least one"):
        await client.complete(
            messages=[{"role": "system", "content": "only system"}],
            model="claude-sonnet-4-6",
            temperature=0.0,
            max_tokens=100,
        )
