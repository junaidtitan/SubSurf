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
        allow_shared_claude_config=False,
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
        allow_shared_claude_config=True,
    )

    with pytest.raises(wizard.WizardError, match="refresh token is invalid"):
        wizard.enroll_and_publish(options)

    assert json.loads(accounts_file.read_text()) == {
        "accounts": [{"id": "old", "label": "old"}],
    }


def test_validate_options_rejects_shared_claude_config(tmp_path: Path):
    options = _options(tmp_path, config_dir="~/.claude", allow_shared=False)

    with pytest.raises(wizard.WizardError, match="Refusing to use"):
        wizard.validate_options(options)


def test_validate_options_allows_shared_config_with_explicit_override(tmp_path: Path):
    options = _options(tmp_path, config_dir="~/.claude", allow_shared=True)

    wizard.validate_options(options)


def test_validate_options_allows_isolated_config(tmp_path: Path):
    options = _options(tmp_path, config_dir="~/.claude-subsurf-default", allow_shared=False)

    wizard.validate_options(options)


def test_resolve_options_rejects_shared_config_before_prompts(monkeypatch):
    monkeypatch.setattr(wizard, "prompt_bool", fail_prompt_bool)

    with pytest.raises(wizard.WizardError, match="Refusing to use"):
        wizard.resolve_options(_args(config_dir="~/.claude", skip_login=True))


def test_resolve_options_skip_login_does_not_prompt_for_launch(monkeypatch):
    monkeypatch.setattr(wizard, "prompt_bool", fail_prompt_bool)

    options = wizard.resolve_options(
        _args(
            config_dir="~/.claude-subsurf-default",
            skip_login=True,
            start_daemon=False,
            attach_dir="./sample-app",
        ),
    )

    assert options.launch_claude is False


def _options(
    tmp_path: Path,
    *,
    config_dir: str,
    allow_shared: bool,
) -> wizard.WizardOptions:
    return wizard.WizardOptions(
        account_id="default",
        label="default",
        config_dir=config_dir,
        token_file=str(tmp_path / "oauth_token"),
        accounts_file=str(tmp_path / "cc_accounts.json"),
        pool_file=str(tmp_path / "oauth_pool.json"),
        interval=30,
        launch_claude=False,
        skip_login=True,
        start_daemon=False,
        attach_dir=None,
        overwrite_attach=False,
        allow_shared_claude_config=allow_shared,
    )


def _args(
    *,
    config_dir: str,
    skip_login: bool,
    start_daemon: bool | None = False,
    attach_dir: str | None = "./sample-app",
) -> argparse.Namespace:
    return argparse.Namespace(
        account_id="default",
        label="default",
        config_dir=config_dir,
        token_file="~/.config/subsurf/oauth_token",
        accounts_file="~/.config/subsurf/cc_accounts.json",
        pool_file="~/.config/subsurf/oauth_pool.json",
        interval=60,
        skip_login=skip_login,
        allow_shared_claude_config=False,
        launch_claude=None,
        start_daemon=start_daemon,
        attach_dir=attach_dir,
        overwrite_attach=True,
    )


def fail_prompt_bool(default: bool, message: str) -> bool:
    raise AssertionError(f"unexpected prompt: {message}")


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
