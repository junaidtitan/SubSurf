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


def test_status_reports_generated_isolation_paths(tmp_path: Path, capsys):
    install_id_file = tmp_path / "install_id"
    install_id_file.write_text("subsurf-abcd1234")
    args = argparse.Namespace(
        account_id=None,
        config_dir=None,
        install_id_file=str(install_id_file),
        token_file=None,
        accounts_file=None,
    )

    assert wizard.status(args) == 0

    out = capsys.readouterr().out
    assert "subsurf-abcd1234" in out
    assert ".claude-subsurf-subsurf-abcd1234" in out
    assert "Claude Code-credentials-" in out


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


def test_resolve_options_auto_defaults_do_not_prompt(tmp_path: Path, monkeypatch):
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
            install_id_file=tmp_path / "install_id",
        ),
    )

    assert options.account_id.startswith("subsurf-")
    assert options.label == options.account_id
    assert options.config_dir.endswith(f".claude-subsurf-{options.account_id}")
    assert options.launch_claude is True
    assert options.start_daemon is True
    assert options.attach_dir == "sample-app"
    assert options.overwrite_attach is True
    assert f"installs/{options.account_id}/oauth_token" in options.token_file
    assert f"installs/{options.account_id}/cc_accounts.json" in options.accounts_file


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


def test_run_claude_login_passes_isolated_config(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run(cmd, *, env):
        calls.append((cmd, env))
        return argparse.Namespace(returncode=0)

    monkeypatch.setattr(wizard.subprocess, "run", fake_run)
    options = _options(
        tmp_path,
        config_dir=str(tmp_path / ".claude-subsurf-acct"),
        allow_shared=False,
    )
    options.skip_login = False
    options.launch_claude = True

    wizard.run_claude_login(options)

    assert calls[0][0] == ["claude"]
    assert calls[0][1]["CLAUDE_CONFIG_DIR"] == str(tmp_path / ".claude-subsurf-acct")


def test_run_claude_login_rejects_shared_config_even_when_called_directly(tmp_path: Path):
    options = _options(tmp_path, config_dir="~/.claude", allow_shared=False)
    options.skip_login = False
    options.launch_claude = True

    with pytest.raises(wizard.WizardError, match="Refusing to use"):
        wizard.run_claude_login(options)


def test_run_wizard_codex_provider_skip_login(tmp_path: Path):
    args = wizard.build_parser().parse_args([
        "--provider",
        "codex",
        "--account-id",
        "acct",
        "--codex-home",
        str(tmp_path / "codex_home"),
        "--codex-model",
        "codex",
        "--skip-login",
        "--attach-dir",
        str(tmp_path / "app"),
    ])

    assert wizard.run_wizard(args) == 0

    assert (tmp_path / "codex_home/config.toml").read_text() == (
        'model = "gpt-5.3-codex"\n\ncli_auth_credentials_store = "file"\n'
    )
    assert (tmp_path / "app/.env.subsurf.codex").exists()


def test_run_wizard_manual_provider_prompt_can_choose_codex(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(wizard, "prompt_provider", lambda: "codex")
    args = wizard.build_parser().parse_args([
        "--manual",
        "--account-id",
        "acct",
        "--codex-home",
        str(tmp_path / "codex_home"),
        "--codex-model",
        "mini",
        "--skip-login",
        "--attach-dir",
        str(tmp_path / "app"),
    ])

    assert wizard.run_wizard(args) == 0

    assert (tmp_path / "codex_home/config.toml").read_text() == (
        'model = "gpt-5.4-mini"\n\ncli_auth_credentials_store = "file"\n'
    )
    assert (tmp_path / "app/.env.subsurf.codex").exists()


def test_should_launch_clear_screen_for_bare_tty():
    args = wizard.build_parser().parse_args([])

    assert wizard.should_launch_clear_screen(
        args,
        stdin=FakeStream(is_tty=True),
        stdout=FakeStream(is_tty=True),
    )


def test_should_not_launch_clear_screen_for_explicit_provider():
    args = wizard.build_parser().parse_args(["--provider", "codex"])

    assert not wizard.should_launch_clear_screen(
        args,
        stdin=FakeStream(is_tty=True),
        stdout=FakeStream(is_tty=True),
    )


def test_should_not_launch_clear_screen_when_disabled():
    args = wizard.build_parser().parse_args(["--no-clear-screen"])

    assert not wizard.should_launch_clear_screen(
        args,
        stdin=FakeStream(is_tty=True),
        stdout=FakeStream(is_tty=True),
    )


def test_no_fullscreen_alias_disables_clear_screen():
    args = wizard.build_parser().parse_args(["--no-fullscreen"])

    assert not wizard.should_launch_clear_screen(
        args,
        stdin=FakeStream(is_tty=True),
        stdout=FakeStream(is_tty=True),
    )


def test_run_clear_screen_wizard_passes_selected_provider(monkeypatch):
    captured = {}

    def fake_run_wizard(args: argparse.Namespace) -> int:
        captured["provider"] = args.provider
        captured["manual"] = args.manual
        return 0

    monkeypatch.setattr(wizard, "cleared_screen_onboarding", lambda: "codex")
    monkeypatch.setattr(wizard, "run_wizard", fake_run_wizard)

    args = wizard.build_parser().parse_args([])

    assert wizard.run_clear_screen_wizard(args) == 0
    assert captured == {"provider": "codex", "manual": False}


def test_cleared_screen_onboarding_can_choose_codex(monkeypatch):
    answers = iter(["", "2", ""])

    monkeypatch.setattr("builtins.input", lambda message: next(answers))
    monkeypatch.setattr(wizard, "write_screen", lambda lines: None)

    assert wizard.cleared_screen_onboarding() == "codex"


def test_run_clear_screen_wizard_handles_eof(monkeypatch):
    monkeypatch.setattr(wizard, "cleared_screen_onboarding", lambda: (_ for _ in ()).throw(EOFError))

    args = wizard.build_parser().parse_args([])

    assert wizard.run_clear_screen_wizard(args) == 130


def test_main_uses_clear_screen_for_bare_tty(monkeypatch):
    calls = []

    monkeypatch.setattr(
        wizard,
        "should_launch_clear_screen",
        lambda args: args.provider is None and not args.no_clear_screen,
    )
    monkeypatch.setattr(wizard, "run_clear_screen_wizard", lambda args: calls.append(args) or 0)

    assert wizard.main([]) == 0
    assert len(calls) == 1


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
    token_file: str | None = None,
    accounts_file: str | None = None,
    pool_file: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        account_id=account_id,
        label=account_id,
        config_dir=config_dir,
        install_id_file=str(install_id_file or Path("/tmp/subsurf-test-install-id")),
        token_file=token_file,
        accounts_file=accounts_file,
        pool_file=pool_file,
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


class FakeStream:
    def __init__(self, *, is_tty: bool):
        self.is_tty = is_tty

    def isatty(self) -> bool:
        return self.is_tty


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
