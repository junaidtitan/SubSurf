from __future__ import annotations

from pathlib import Path

import pytest

from subsurf import setup_tui, wizard


def test_auto_wizard_args_generate_isolated_setup(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(wizard, "prompt", fail_prompt)
    monkeypatch.setattr(wizard, "prompt_bool", fail_prompt_bool)

    install_id_file = tmp_path / "install_id"
    args = setup_tui.build_parser().parse_args([
        "--install-id-file",
        str(install_id_file),
        "--skip-login",
        "--no-start-daemon",
    ])

    options = wizard.resolve_options(setup_tui.auto_wizard_args(args))

    assert options.account_id.startswith("subsurf-")
    assert options.label == options.account_id
    assert options.config_dir.endswith(f".claude-subsurf-{options.account_id}")
    assert options.attach_dir == "sample-app"
    assert options.overwrite_attach is True
    assert options.start_daemon is False
    assert f"installs/{options.account_id}/oauth_token" in options.token_file
    assert f"installs/{options.account_id}/cc_accounts.json" in options.accounts_file
    assert install_id_file.read_text().strip() == options.account_id


def test_auto_wizard_args_honor_explicit_account_and_no_overwrite(tmp_path: Path):
    install_id_file = tmp_path / "install_id"
    args = setup_tui.build_parser().parse_args([
        "--account-id",
        "work",
        "--install-id-file",
        str(install_id_file),
        "--skip-login",
        "--no-overwrite-attach",
    ])

    options = wizard.resolve_options(setup_tui.auto_wizard_args(args))

    assert options.account_id == "work"
    assert options.label == "work"
    assert options.config_dir.endswith(".claude-subsurf-work")
    assert options.overwrite_attach is False
    assert not install_id_file.exists()


def test_capture_collects_output():
    def emit() -> str:
        print("hello")
        return "ok"

    captured = setup_tui.capture(emit)

    assert captured.value == "ok"
    assert captured.output == "hello\n"


@pytest.mark.asyncio
async def test_app_mounts_headlessly_when_textual_is_installed():
    if setup_tui.TEXTUAL_IMPORT_ERROR is not None:
        pytest.skip("Textual is not installed")

    app = setup_tui.SubSurfSetupApp(setup_tui.build_parser().parse_args(["--skip-login"]))

    async with app.run_test():
        assert app.args.skip_login is True


def fail_prompt(default: str, message: str) -> str:
    raise AssertionError(f"unexpected prompt: {message}")


def fail_prompt_bool(default: bool, message: str) -> bool:
    raise AssertionError(f"unexpected prompt: {message}")
