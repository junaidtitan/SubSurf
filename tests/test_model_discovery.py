from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from subsurf import model_discovery
from subsurf.model_discovery import DiscoveredModel, ModelDiscoveryError


def test_parse_openai_style_model_payload():
    models = model_discovery.parse_model_payload(
        {
            "object": "list",
            "data": [
                {"id": "gpt-account-a", "created": 123, "owned_by": "openai"},
                {"id": "gpt-account-a", "created": 123, "owned_by": "openai"},
                {"id": "gpt-account-b"},
            ],
        },
        owner="openai",
    )

    assert [model.id for model in models] == ["gpt-account-a", "gpt-account-b"]
    assert models[0].created == 123
    assert models[0].owned_by == "openai"


def test_parse_codex_style_model_payload():
    models = model_discovery.parse_model_payload(
        {"models": [{"slug": "gpt-5.3-codex", "name": "GPT-5.3 Codex"}]},
        owner="chatgpt",
    )

    assert models == [
        DiscoveredModel(
            id="gpt-5.3-codex",
            owned_by="chatgpt",
            display_name="GPT-5.3 Codex",
        ),
    ]


def test_discover_openai_models_uses_api_key_and_writes_cache(tmp_path: Path):
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, headers: dict[str, str], timeout: float):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return {"data": [{"id": "gpt-account"}]}

    cache_file = tmp_path / "models.json"

    models = model_discovery.discover_openai_models(
        "sk-test",
        cache_file=cache_file,
        http_get=fake_get,
    )

    assert [model.id for model in models] == ["gpt-account"]
    assert calls[0]["url"] == model_discovery.OPENAI_MODELS_URL
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert json.loads(cache_file.read_text())["data"][0]["id"] == "gpt-account"


def test_discover_chatgpt_codex_models_uses_codex_backend_and_account_header():
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, headers: dict[str, str], timeout: float):
        calls.append({"url": url, "headers": headers})
        return {"models": [{"slug": "gpt-5.3-codex"}]}

    models = model_discovery.discover_chatgpt_codex_models(
        "access-token",
        account_id="workspace-1",
        http_get=fake_get,
    )

    assert [model.id for model in models] == ["gpt-5.3-codex"]
    assert calls[0]["url"] == model_discovery.CHATGPT_CODEX_MODELS_URL
    assert calls[0]["headers"]["Authorization"] == "Bearer access-token"
    assert calls[0]["headers"]["ChatGPT-Account-ID"] == "workspace-1"


def test_discover_anthropic_models_uses_oauth_bearer_headers(tmp_path: Path):
    token_file = tmp_path / "oauth_token"
    token_file.write_text("anthropic-token")
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, headers: dict[str, str], timeout: float):
        calls.append({"url": url, "headers": headers})
        return {"data": [{"id": "claude-account-model"}]}

    models = model_discovery.discover_anthropic_models(token_file, http_get=fake_get)

    assert [model.id for model in models] == ["claude-account-model"]
    assert calls[0]["url"] == model_discovery.ANTHROPIC_MODELS_URL
    assert calls[0]["headers"]["Authorization"] == "Bearer anthropic-token"
    assert calls[0]["headers"]["anthropic-version"] == "2023-06-01"


def test_read_model_cache_returns_cached_models(tmp_path: Path):
    cache_file = tmp_path / "models.json"
    model_discovery.write_model_cache(
        cache_file,
        provider="openai",
        models=[DiscoveredModel(id="cached-model", owned_by="openai")],
    )

    assert [model.id for model in model_discovery.read_model_cache(cache_file)] == [
        "cached-model",
    ]


def test_parse_model_payload_rejects_missing_model_list():
    with pytest.raises(ModelDiscoveryError, match="model list"):
        model_discovery.parse_model_payload({"object": "list"}, owner="openai")
