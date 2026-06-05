from __future__ import annotations

import subprocess
import sys

from subsurf import model_discovery
from subsurf.models import (
    model_ids,
    openai_model_entries,
    resolve_model_id,
    strip_provider_prefix,
    supports_sampling,
)
from subsurf.model_discovery import DiscoveredModel
from subsurf.openai_models import (
    choose_available_model,
    model_ids as openai_model_ids,
    resolve_model_id as resolve_openai_model_id,
)


def test_resolve_current_claude_code_family_aliases():
    assert resolve_model_id("opus") == "claude-opus-4-8"
    assert resolve_model_id("sonnet") == "claude-sonnet-4-6"
    assert resolve_model_id("haiku") == "claude-haiku-4-5-20251001"


def test_resolve_provider_prefixed_aliases():
    assert resolve_model_id("subsurf/sonnet") == "claude-sonnet-4-6"
    assert resolve_model_id("anthropic_oauth/haiku") == "claude-haiku-4-5-20251001"


def test_unknown_full_model_ids_pass_through():
    assert resolve_model_id("claude-sonnet-9-9") == "claude-sonnet-9-9"


def test_sampling_support_tracks_opus_4_7_and_later():
    assert supports_sampling("claude-sonnet-4-6")
    assert supports_sampling("claude-opus-4-6")
    assert not supports_sampling("opus")
    assert not supports_sampling("claude-opus-4-7")
    assert not supports_sampling("claude-opus-4-8")


def test_strip_provider_prefix():
    assert strip_provider_prefix("subsurf/claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert strip_provider_prefix("claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_model_list_includes_current_families():
    ids = set(model_ids(include_aliases=True, provider_prefix="subsurf/"))
    assert "subsurf/opus" in ids
    assert "subsurf/sonnet" in ids
    assert "subsurf/haiku" in ids
    assert "subsurf/claude-opus-4-8" in ids
    assert "subsurf/claude-sonnet-4-6" in ids
    assert "subsurf/claude-haiku-4-5-20251001" in ids


def test_openai_model_entries_shape():
    entries = openai_model_entries()
    assert entries
    assert entries[0]["object"] == "model"
    assert entries[0]["owned_by"] == "subsurf"


def test_openai_model_entries_prefers_dynamic_account_models(monkeypatch, tmp_path):
    token_file = tmp_path / "oauth_token"
    token_file.write_text("token")

    def fake_discover(token_path, *, cache_file=None):
        assert token_path == token_file
        assert cache_file == token_file.parent / "claude_models.json"
        return [DiscoveredModel(id="claude-account-model", owned_by="anthropic")]

    monkeypatch.setattr(model_discovery, "discover_anthropic_models", fake_discover)

    entries = openai_model_entries(token_path=token_file)
    ids = [entry["id"] for entry in entries]

    assert ids[0] == "subsurf/claude-account-model"
    assert "subsurf/sonnet" in ids


def test_models_module_runs_without_import_warning():
    result = subprocess.run(
        [sys.executable, "-W", "error", "-m", "subsurf.models"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "claude-opus-4-8" in result.stdout


def test_openai_model_aliases_include_current_gpt_families():
    assert resolve_openai_model_id("latest") == "gpt-5.5"
    assert resolve_openai_model_id("mini") == "gpt-5.4-mini"
    assert resolve_openai_model_id("codex") == "gpt-5.3-codex"
    assert resolve_openai_model_id("spark") == "gpt-5.3-codex-spark"
    assert resolve_openai_model_id("chat") == "chat-latest"
    assert resolve_openai_model_id("gpt-new-explicit") == "gpt-new-explicit"

    ids = set(openai_model_ids(include_aliases=True))
    assert "gpt-5.5" in ids
    assert "gpt-5.4" in ids
    assert "gpt-5.4-mini" in ids
    assert "gpt-5.4-nano" in ids
    assert "gpt-5.3-codex" in ids
    assert "gpt-5.2-codex" in ids
    assert "gpt-5.1-codex" in ids
    assert "gpt-5-codex" in ids
    assert "gpt-5.3-chat-latest" in ids
    assert "chat-latest" in ids
    assert "gpt-4.1" in ids
    assert "gpt-4-turbo" in ids
    assert "gpt-3.5-turbo" in ids


def test_choose_available_openai_model_prefers_account_availability():
    assert choose_available_model(["gpt-5.4-mini", "gpt-5.3-codex"]) == "gpt-5.3-codex"
    assert choose_available_model(["gpt-5.4-mini"], requested="mini") == "gpt-5.4-mini"
    assert choose_available_model(["gpt-5.4-mini"], requested="gpt-new") == "gpt-new"


def test_openai_models_module_runs_without_import_warning():
    result = subprocess.run(
        [sys.executable, "-W", "error", "-m", "subsurf.openai_models"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "gpt-5.5" in result.stdout
