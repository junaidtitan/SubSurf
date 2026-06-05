from __future__ import annotations

import argparse
from pathlib import Path

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
