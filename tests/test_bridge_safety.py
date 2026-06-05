from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import cc_session_bridge as bridge


def test_tick_multi_skips_legacy_accounts_without_isolation_metadata(tmp_path: Path, monkeypatch):
    account = {
        "id": "legacy",
        "label": "legacy",
        "accessToken": "old-access",
        "refreshToken": "old-refresh",
        "expiresAt": 0,
    }

    def fail_refresh(_account):
        raise AssertionError("legacy account should not refresh")

    monkeypatch.setattr(bridge, "refresh", fail_refresh)

    bridge.tick_multi(_args(tmp_path, force_refresh=True), [account])

    assert (tmp_path / "oauth_token_legacy").read_text() == "old-access"


def test_tick_multi_skips_shared_claude_keychain_accounts(tmp_path: Path, monkeypatch):
    account = {
        "id": "shared",
        "label": "shared",
        "configDir": "~/.claude",
        "keychainService": bridge.KEYCHAIN_SERVICE,
        "accessToken": "old-access",
        "refreshToken": "old-refresh",
        "expiresAt": 0,
    }

    def fail_refresh(_account):
        raise AssertionError("shared account should not refresh")

    monkeypatch.setattr(bridge, "refresh", fail_refresh)

    bridge.tick_multi(_args(tmp_path, force_refresh=True), [account])

    assert (tmp_path / "oauth_token_shared").read_text() == "old-access"


def test_tick_multi_refreshes_isolated_accounts(tmp_path: Path, monkeypatch):
    accounts_file = tmp_path / "cc_accounts.json"
    account = {
        "id": "safe",
        "label": "safe",
        "configDir": "~/.claude-subsurf-safe",
        "keychainService": "Claude Code-credentials-12345678",
        "accessToken": "old-access",
        "refreshToken": "old-refresh",
        "expiresAt": 0,
    }

    def fake_refresh(_account):
        return {
            "accessToken": "new-access",
            "refreshToken": "new-refresh",
            "expiresAt": 9999999999999,
        }

    monkeypatch.setattr(bridge, "refresh", fake_refresh)

    bridge.tick_multi(_args(tmp_path, accounts_file=accounts_file, force_refresh=True), [account])

    assert (tmp_path / "oauth_token_safe").read_text() == "new-access"
    saved = json.loads(accounts_file.read_text())["accounts"][0]
    assert saved["accessToken"] == "new-access"
    assert saved["refreshToken"] == "new-refresh"


def test_bridge_cli_rejects_default_shared_source():
    args = argparse.Namespace(
        allow_shared_claude_config=False,
        service=bridge.KEYCHAIN_SERVICE,
    )

    assert bridge.reject_shared_claude_source(args) == 2


def _args(
    tmp_path: Path,
    *,
    accounts_file: Path | None = None,
    force_refresh: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        token_file=str(tmp_path / "oauth_token"),
        pool_file=str(tmp_path / "oauth_pool.json"),
        accounts_file=str(accounts_file or tmp_path / "cc_accounts.json"),
        skew=600,
        force_refresh=force_refresh,
        push=False,
    )
