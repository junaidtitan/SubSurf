from __future__ import annotations

from pathlib import Path

import pytest

from subsurf.anthropic_oauth import (
    AnthropicOAuthClient,
    OAuthTokenMissing,
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
