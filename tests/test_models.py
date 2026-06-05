from __future__ import annotations

import subprocess
import sys

from subsurf.models import (
    model_ids,
    openai_model_entries,
    resolve_model_id,
    strip_provider_prefix,
    supports_sampling,
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


def test_models_module_runs_without_import_warning():
    result = subprocess.run(
        [sys.executable, "-W", "error", "-m", "subsurf.models"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "claude-opus-4-8" in result.stdout
