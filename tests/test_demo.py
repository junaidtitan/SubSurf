from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from subsurf.demo import (
    DemoPaths,
    first_account_id,
    resolve_demo_paths,
    token_ready,
    write_sample_app,
)


def test_first_account_id(tmp_path: Path):
    accounts = tmp_path / "cc_accounts.json"
    accounts.write_text(json.dumps({"accounts": [{"id": "default"}, {"id": "second"}]}))

    assert first_account_id(accounts) == "default"


def test_token_ready(tmp_path: Path):
    token = tmp_path / "oauth_token"
    assert not token_ready(token)
    token.write_text("")
    assert not token_ready(token)
    token.write_text("sk-ant-oat01-test")
    assert token_ready(token)


def test_resolve_demo_paths_prefers_account_token(tmp_path: Path, monkeypatch):
    accounts = tmp_path / "cc_accounts.json"
    accounts.write_text(json.dumps({"accounts": [{"id": "default"}]}))
    token_base = tmp_path / "oauth_token"
    account_token = tmp_path / "oauth_token_default"
    account_token.write_text("token")
    monkeypatch.delenv("SUBSURF_OAUTH_TOKEN_PATH", raising=False)

    args = _args(tmp_path, token_base=token_base, accounts_file=accounts)
    paths = resolve_demo_paths(args)

    assert paths.account_id == "default"
    assert paths.token_path == account_token


def test_resolve_demo_paths_honors_env_token(tmp_path: Path, monkeypatch):
    env_token = tmp_path / "env_token"
    monkeypatch.setenv("SUBSURF_OAUTH_TOKEN_PATH", str(env_token))

    paths = resolve_demo_paths(_args(tmp_path))

    assert paths.token_path == env_token


def test_write_sample_app(tmp_path: Path):
    paths = DemoPaths(
        token_base=tmp_path / "oauth_token",
        token_path=tmp_path / "oauth_token_default",
        accounts_file=tmp_path / "cc_accounts.json",
        pool_file=tmp_path / "oauth_pool.json",
        app_dir=tmp_path / "sample-app",
        account_id="default",
    )

    write_sample_app(paths)

    assert (paths.app_dir / ".env.subsurf").exists()
    assert (paths.app_dir / "subsurf_client_example.py").exists()
    assert "oauth_token_default" in (paths.app_dir / ".env.subsurf").read_text()


def _args(
    tmp_path: Path,
    *,
    token_base: Path | None = None,
    accounts_file: Path | None = None,
):
    return Namespace(
        account_id=None,
        app_dir=str(tmp_path / "sample-app"),
        token_file=str(token_base or tmp_path / "oauth_token"),
        accounts_file=str(accounts_file or tmp_path / "cc_accounts.json"),
        pool_file=str(tmp_path / "oauth_pool.json"),
    )
