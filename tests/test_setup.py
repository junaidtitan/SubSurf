from __future__ import annotations

from pathlib import Path

from subsurf import setup, wizard


def test_wizard_args_generate_isolated_setup(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(wizard, "prompt", fail_prompt)
    monkeypatch.setattr(wizard, "prompt_bool", fail_prompt_bool)

    install_id_file = tmp_path / "install_id"
    args = setup.build_parser().parse_args([
        "--install-id-file",
        str(install_id_file),
        "--skip-login",
        "--no-start-daemon",
    ])

    options = wizard.resolve_options(setup.wizard_args(args))

    assert options.account_id.startswith("subsurf-")
    assert options.label == options.account_id
    assert options.config_dir.endswith(f".claude-subsurf-{options.account_id}")
    assert options.attach_dir == "sample-app"
    assert options.overwrite_attach is True
    assert options.start_daemon is False
    assert f"installs/{options.account_id}/oauth_token" in options.token_file
    assert f"installs/{options.account_id}/cc_accounts.json" in options.accounts_file
    assert install_id_file.read_text().strip() == options.account_id


def test_wizard_args_honor_explicit_account_and_no_overwrite(tmp_path: Path):
    install_id_file = tmp_path / "install_id"
    args = setup.build_parser().parse_args([
        "--account-id",
        "work",
        "--install-id-file",
        str(install_id_file),
        "--skip-login",
        "--no-overwrite-attach",
    ])

    options = wizard.resolve_options(setup.wizard_args(args))

    assert options.account_id == "work"
    assert options.label == "work"
    assert options.config_dir.endswith(".claude-subsurf-work")
    assert options.overwrite_attach is False
    assert not install_id_file.exists()


def test_write_sample_app(tmp_path: Path):
    options = wizard.WizardOptions(
        account_id="acct",
        label="acct",
        config_dir=str(tmp_path / ".claude-subsurf-acct"),
        token_file=str(tmp_path / "oauth_token"),
        accounts_file=str(tmp_path / "cc_accounts.json"),
        pool_file=str(tmp_path / "oauth_pool.json"),
        interval=60,
        launch_claude=False,
        skip_login=True,
        start_daemon=False,
        attach_dir=str(tmp_path / "sample-app"),
        overwrite_attach=True,
        allow_shared_claude_config=False,
    )

    setup.write_sample_app(options)

    assert (tmp_path / "sample-app/.env.subsurf").exists()
    assert (tmp_path / "sample-app/subsurf_client_example.py").exists()


def fail_prompt(default: str, message: str) -> str:
    raise AssertionError(f"unexpected prompt: {message}")


def fail_prompt_bool(default: bool, message: str) -> bool:
    raise AssertionError(f"unexpected prompt: {message}")
