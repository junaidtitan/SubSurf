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


def test_resolve_options_auto_defaults_do_not_prompt(monkeypatch):
    monkeypatch.setattr(wizard, "prompt", fail_prompt)
    monkeypatch.setattr(wizard, "prompt_bool", fail_prompt_bool)
    monkeypatch.setattr(wizard.shutil, "which", lambda name: "/opt/homebrew/bin/claude")

    options = wizard.resolve_options(
        _args(
            config_dir=None,
            skip_login=False,
            start_daemon=None,
            attach_dir=None,
            account_id=None,
        ),
    )

    assert options.account_id.startswith("subsurf-")
    assert options.label == options.account_id
    assert options.config_dir.endswith(f".claude-subsurf-{options.account_id}")
    assert options.launch_claude is True
    assert options.start_daemon is True
    assert options.attach_dir == "sample-app"
    assert options.overwrite_attach is True


def test_resolve_options_reuses_generated_install_id(tmp_path: Path, monkeypatch):
    install_id_file = tmp_path / "install_id"
    monkeypatch.setattr(wizard, "prompt", fail_prompt)
    monkeypatch.setattr(wizard, "prompt_bool", fail_prompt_bool)

    first = wizard.resolve_options(
        _args(
            config_dir=None,
            skip_login=True,
            account_id=None,
            install_id_file=install_id_file,
        ),
    )
    second = wizard.resolve_options(
        _args(
            config_dir=None,
            skip_login=True,
            account_id=None,
            install_id_file=install_id_file,
        ),
    )

    assert first.account_id == second.account_id
    assert install_id_file.read_text().strip() == first.account_id


def test_resolve_options_explicit_account_id_does_not_create_install_id(tmp_path: Path):
    install_id_file = tmp_path / "install_id"

    options = wizard.resolve_options(
        _args(
            config_dir=None,
            skip_login=True,
            account_id="explicit",
            install_id_file=install_id_file,
        ),
    )

    assert options.account_id == "explicit"
    assert not install_id_file.exists()


def test_run_claude_login_skip_login_does_not_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(wizard, "prompt", fail_prompt)
    monkeypatch.setattr(wizard, "prompt_bool", fail_prompt_bool)
    options = _options(
        tmp_path,
        config_dir="~/.claude-subsurf-default",
        allow_shared=False,
    )

    wizard.run_claude_login(options)


def test_running_pid_from_file_handles_stale_pid(tmp_path: Path):
    pid_file = tmp_path / "pid"
    pid_file.write_text("999999999")

    assert wizard.running_pid_from_file(pid_file) is None


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
    config_dir: str | None,
    skip_login: bool,
    account_id: str | None = "default",
    install_id_file: Path | None = None,
    start_daemon: bool | None = False,
    attach_dir: str | None = "./sample-app",
    overwrite_attach: bool | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        account_id=account_id,
        label=account_id,
        config_dir=config_dir,
        install_id_file=str(install_id_file or Path("/tmp/subsurf-test-install-id")),
        token_file="~/.config/subsurf/oauth_token",
        accounts_file="~/.config/subsurf/cc_accounts.json",
        pool_file="~/.config/subsurf/oauth_pool.json",
        interval=60,
        manual=False,
        skip_login=skip_login,
        allow_shared_claude_config=False,
        launch_claude=None,
        start_daemon=start_daemon,
        attach_dir=attach_dir,
        overwrite_attach=overwrite_attach,
    )


def fail_prompt_bool(default: bool, message: str) -> bool:
    raise AssertionError(f"unexpected prompt: {message}")


def fail_prompt(default: str, message: str) -> str:
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
