from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from subsurf import wizard


def test_daemon_command_uses_bridge_script(tmp_path: Path):
    options = wizard.WizardOptions(
        account_id="acct1",
        label="acct1",
        config_dir=str(tmp_path / ".claude-acct1"),
        token_file=str(tmp_path / "oauth_token"),
        accounts_file=str(tmp_path / "cc_accounts.json"),
        pool_file=str(tmp_path / "oauth_pool.json"),
        interval=30,
        launch_claude=False,
        skip_login=True,
        start_daemon=False,
        attach_dir=None,
        overwrite_attach=False,
    )
    command = wizard.daemon_command(options)
    assert command[0]
    assert "cc_session_bridge.py" in command[1]
    assert "--interval" in command
    assert "30" in command


def test_status_handles_missing_files(tmp_path: Path, capsys):
    args = argparse.Namespace(
        token_file=str(tmp_path / "oauth_token"),
        accounts_file=str(tmp_path / "cc_accounts.json"),
    )
    assert wizard.status(args) == 0
    out = capsys.readouterr().out
    assert "missing" in out


def test_enroll_and_publish_rolls_back_invalid_grant(tmp_path: Path, monkeypatch):
    accounts_file = tmp_path / "cc_accounts.json"
    accounts_file.write_text(json.dumps({"accounts": [{"id": "old", "label": "old"}]}))
    fake_bridge = FakeBridge()
    monkeypatch.setattr(wizard, "bridge_module", lambda: fake_bridge)

    options = wizard.WizardOptions(
        account_id="default",
        label="default",
        config_dir="~/.claude",
        token_file=str(tmp_path / "oauth_token"),
        accounts_file=str(accounts_file),
        pool_file=str(tmp_path / "oauth_pool.json"),
        interval=30,
        launch_claude=False,
        skip_login=True,
        start_daemon=False,
        attach_dir=None,
        overwrite_attach=False,
    )

    with pytest.raises(wizard.WizardError, match="refresh token is invalid"):
        wizard.enroll_and_publish(options)

    assert json.loads(accounts_file.read_text()) == {
        "accounts": [{"id": "old", "label": "old"}],
    }


class FakeBridge:
    DEFAULT_ACCOUNT = "jq"

    @staticmethod
    def keychain_service_for_config_dir(config_dir: str) -> str:
        return f"service:{config_dir}"

    @staticmethod
    def load_accounts(path: str):
        return json.loads(Path(path).read_text()).get("accounts", [])

    @staticmethod
    def save_accounts(path: str, accounts):
        Path(path).write_text(json.dumps({"accounts": accounts}))

    @staticmethod
    def enroll_from_keychain(args: argparse.Namespace) -> int:
        Path(args.accounts_file).write_text(json.dumps({
            "accounts": [{"id": args.enroll, "label": args.label}],
        }))
        return 0

    @staticmethod
    def tick(args: argparse.Namespace) -> None:
        raise RuntimeError(
            'refresh HTTP 400: {"error": "invalid_grant", '
            '"error_description": "Refresh token not found or invalid"}',
        )
