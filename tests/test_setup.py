from __future__ import annotations

from pathlib import Path

from subsurf import codex_auth, setup, wizard


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


def test_codex_setup_skip_login_prepares_isolated_home(tmp_path: Path):
    install_id_file = tmp_path / "install_id"
    codex_home = tmp_path / "codex_home"
    args = setup.build_parser().parse_args([
        "--provider",
        "codex",
        "--install-id-file",
        str(install_id_file),
        "--codex-home",
        str(codex_home),
        "--app-dir",
        str(tmp_path / "app"),
        "--codex-model",
        "mini",
        "--skip-login",
        "--no-live-checks",
    ])

    assert setup.run_setup(args) == 0

    account_id = install_id_file.read_text().strip()
    assert account_id.startswith("subsurf-")
    assert (codex_home / "config.toml").read_text() == (
        'model = "gpt-5.4-mini"\n\ncli_auth_credentials_store = "file"\n'
    )
    assert (tmp_path / "app/.env.subsurf.codex").exists()
    env_text = (tmp_path / "app/.env.subsurf.codex").read_text()
    assert f"--account-id {account_id}" in env_text
    assert f"--codex-home {codex_home}" in env_text


def test_codex_setup_rejects_shared_codex_home(tmp_path: Path):
    args = setup.build_parser().parse_args([
        "--provider",
        "codex",
        "--account-id",
        "acct",
        "--codex-home",
        "~/.codex",
        "--skip-login",
    ])

    try:
        setup.run_setup(args)
    except codex_auth.CodexAuthError as exc:
        assert "Refusing to use" in str(exc)
    else:
        raise AssertionError("expected shared CODEX_HOME rejection")


def test_refresh_codex_model_selection_prefers_discovered_default(tmp_path: Path, monkeypatch):
    paths = codex_auth.paths_for_account("acct", codex_home=tmp_path / "codex_home")
    codex_auth.ensure_codex_home(paths, model="gpt-5.5")

    monkeypatch.setattr(
        setup.codex_auth,
        "discover_models",
        lambda paths: [
            codex_auth.model_discovery.DiscoveredModel(id="gpt-5.4-mini"),
            codex_auth.model_discovery.DiscoveredModel(id="gpt-5.3-codex"),
        ],
    )

    selected = setup.refresh_codex_model_selection(
        paths,
        requested_model=None,
        current_model="gpt-5.5",
        allow_shared=False,
    )

    assert selected == "gpt-5.3-codex"
    assert 'model = "gpt-5.3-codex"' in paths.config_file.read_text()


def test_refresh_codex_model_selection_keeps_explicit_model(tmp_path: Path, monkeypatch):
    paths = codex_auth.paths_for_account("acct", codex_home=tmp_path / "codex_home")
    codex_auth.ensure_codex_home(paths, model="gpt-5.5")

    monkeypatch.setattr(
        setup.codex_auth,
        "discover_models",
        lambda paths: [codex_auth.model_discovery.DiscoveredModel(id="gpt-5.4-mini")],
    )

    selected = setup.refresh_codex_model_selection(
        paths,
        requested_model="gpt-explicit",
        current_model="gpt-explicit",
        allow_shared=False,
    )

    assert selected == "gpt-explicit"


def fail_prompt(default: str, message: str) -> str:
    raise AssertionError(f"unexpected prompt: {message}")


def fail_prompt_bool(default: bool, message: str) -> bool:
    raise AssertionError(f"unexpected prompt: {message}")
