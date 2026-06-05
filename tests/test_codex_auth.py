from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import pytest

from subsurf import codex_auth


def test_paths_for_account_uses_isolated_codex_home(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(codex_auth, "DEFAULT_INSTALLS_DIR", str(tmp_path / "installs"))

    paths = codex_auth.paths_for_account("subsurf-abcd1234")

    assert paths.codex_home == tmp_path / "installs/subsurf-abcd1234/codex_home"
    assert paths.auth_file == paths.codex_home / "auth.json"


def test_ensure_codex_home_forces_file_storage_and_model(tmp_path: Path):
    paths = codex_auth.paths_for_account("acct", codex_home=tmp_path / "codex_home")
    paths.config_file.parent.mkdir(parents=True)
    paths.config_file.write_text(
        'model = "gpt-5.4"\nmodel_provider = "openai"\n'
        'cli_auth_credentials_store = "keyring"\n',
    )

    codex_auth.ensure_codex_home(paths, model="mini")

    assert paths.config_file.read_text() == (
        'model = "gpt-5.4-mini"\nmodel_provider = "openai"\n'
        'cli_auth_credentials_store = "file"\n'
    )


def test_ensure_codex_home_adds_file_storage_to_new_config(tmp_path: Path):
    paths = codex_auth.paths_for_account("acct", codex_home=tmp_path / "codex_home")

    codex_auth.ensure_codex_home(paths)

    assert paths.config_file.read_text() == 'cli_auth_credentials_store = "file"\n'


def test_validate_codex_home_rejects_shared_default():
    paths = codex_auth.paths_for_account("acct", codex_home="~/.codex")

    with pytest.raises(codex_auth.CodexAuthError, match="Refusing to use"):
        codex_auth.validate_codex_home(paths)


def test_validate_codex_home_allows_shared_with_explicit_override():
    paths = codex_auth.paths_for_account("acct", codex_home="~/.codex")

    codex_auth.validate_codex_home(paths, allow_shared=True)


def test_status_summarizes_chatgpt_auth_with_jwt_claims():
    id_token = _jwt({
        "email": "user@example.com",
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "workspace-1",
            "chatgpt_plan_type": "plus",
        },
    })
    status = codex_auth.summarize_auth({
        "auth_mode": "chatgpt",
        "tokens": {
            "id_token": id_token,
            "access_token": "access-123",
            "refresh_token": "refresh-123",
        },
    })

    assert status.exists is True
    assert status.mode == "chatgpt"
    assert status.has_access_token is True
    assert status.has_refresh_token is True
    assert status.account_id == "workspace-1"
    assert status.email == "user@example.com"
    assert status.plan_type == "plus"


def test_extract_token_prefers_chatgpt_access_token():
    token = codex_auth.extract_token({
        "OPENAI_API_KEY": "sk-test",
        "tokens": {"access_token": "access-123"},
    })

    assert token == "access-123"


def test_extract_token_can_return_api_key():
    token = codex_auth.extract_token({"OPENAI_API_KEY": "sk-test"}, kind="api-key")

    assert token == "sk-test"


def test_token_command_prints_token(tmp_path: Path, capsys):
    paths = codex_auth.paths_for_account("acct", codex_home=tmp_path / "codex_home")
    paths.codex_home.mkdir(parents=True)
    paths.auth_file.write_text(json.dumps({"tokens": {"access_token": "access-123"}}))

    rc = codex_auth.main([
        "token",
        "--account-id",
        "acct",
        "--codex-home",
        str(paths.codex_home),
    ])

    assert rc == 0
    assert capsys.readouterr().out.strip() == "access-123"


def test_models_command_does_not_require_install_id(capsys):
    rc = codex_auth.main(["models"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "gpt-5.5" in out
    assert "gpt-5.4-mini" in out


def test_live_models_command_uses_isolated_auth(monkeypatch, tmp_path: Path, capsys):
    paths = codex_auth.paths_for_account("acct", codex_home=tmp_path / "codex_home")
    calls = []

    def fake_discover(discovered_paths):
        calls.append(discovered_paths)
        return [
            codex_auth.model_discovery.DiscoveredModel(id="gpt-account-model"),
        ]

    monkeypatch.setattr(codex_auth, "discover_models", fake_discover)

    rc = codex_auth.main([
        "models",
        "--live",
        "--account-id",
        "acct",
        "--codex-home",
        str(paths.codex_home),
    ])

    assert rc == 0
    assert calls == [paths]
    assert capsys.readouterr().out.strip() == "gpt-account-model"


def test_discover_models_uses_openai_api_key_auth(tmp_path: Path):
    paths = codex_auth.paths_for_account("acct", codex_home=tmp_path / "codex_home")
    paths.codex_home.mkdir(parents=True)
    paths.auth_file.write_text(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-test"}))
    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return {"data": [{"id": "gpt-account-model"}]}

    models = codex_auth.discover_models(paths, http_get=fake_get)

    assert [model.id for model in models] == ["gpt-account-model"]
    assert calls[0][0] == codex_auth.model_discovery.OPENAI_MODELS_URL
    assert calls[0][1]["Authorization"] == "Bearer sk-test"
    assert [model.id for model in codex_auth.model_discovery.read_model_cache(
        codex_auth.model_cache_file(paths),
    )] == ["gpt-account-model"]


def test_discover_models_uses_chatgpt_codex_auth(tmp_path: Path):
    paths = codex_auth.paths_for_account("acct", codex_home=tmp_path / "codex_home")
    paths.codex_home.mkdir(parents=True)
    paths.auth_file.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": "access-123",
            "account_id": "workspace-1",
        },
    }))
    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return {"models": [{"slug": "gpt-5.3-codex"}]}

    models = codex_auth.discover_models(paths, http_get=fake_get)

    assert [model.id for model in models] == ["gpt-5.3-codex"]
    assert calls[0][0] == codex_auth.model_discovery.CHATGPT_CODEX_MODELS_URL
    assert calls[0][1]["Authorization"] == "Bearer access-123"
    assert calls[0][1]["ChatGPT-Account-ID"] == "workspace-1"


def test_login_command_sets_isolated_codex_home(monkeypatch, tmp_path: Path):
    calls = []
    paths = codex_auth.paths_for_account("acct", codex_home=tmp_path / "codex_home")

    def fake_run(command, *, env):
        calls.append((command, env))
        return argparse.Namespace(returncode=0)

    monkeypatch.setattr(codex_auth.shutil, "which", lambda name: "/usr/local/bin/codex")
    monkeypatch.setattr(codex_auth.subprocess, "run", fake_run)

    rc = codex_auth.main([
        "login",
        "--account-id",
        "acct",
        "--codex-home",
        str(paths.codex_home),
        "--device-auth",
    ])

    assert rc == 0
    assert calls[0][0] == ["codex", "login", "--device-auth"]
    assert calls[0][1]["CODEX_HOME"] == str(paths.codex_home)
    assert paths.config_file.read_text() == (
        'model = "gpt-5.5"\n\ncli_auth_credentials_store = "file"\n'
    )


def test_attach_writes_codex_env_and_examples(tmp_path: Path):
    paths = codex_auth.paths_for_account("acct", codex_home=tmp_path / "codex_home")
    plan = codex_auth.build_attach_plan(tmp_path / "app", paths)

    written = codex_auth.write_attach_files(plan, overwrite=True)

    assert plan.env_file in written
    env_text = plan.env_file.read_text()
    assert f"SUBSURF_CODEX_HOME={paths.codex_home}" in env_text
    assert "CODEX_HOME=" in env_text
    assert f"--codex-home {paths.codex_home}" in env_text
    assert (tmp_path / "app/subsurf_codex_cli_example.py").exists()
    assert (tmp_path / "app/subsurf_codex_token_example.py").exists()


def _jwt(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"
