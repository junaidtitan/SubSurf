from __future__ import annotations

from pathlib import Path

from subsurf import attach
from subsurf.attach import build_attach_plan, build_env, token_path_for_account, write_attach_files
from subsurf.config import SubSurfSettings


def test_token_path_for_account():
    assert token_path_for_account("acct1", "/tmp/oauth_token") == Path("/tmp/oauth_token_acct1")
    assert token_path_for_account(None, "/tmp/oauth_token") == Path("/tmp/oauth_token")


def test_build_env():
    settings = SubSurfSettings(reasoning_model="claude-test")
    env = build_env(settings, Path("/tmp/token"))
    assert env["SUBSURF_OAUTH_TOKEN_PATH"] == "/tmp/token"
    assert env["SUBSURF_REASONING_MODEL"] == "claude-test"
    assert env["SUBSURF_OAUTH_SPOOF"] == "1"


def test_write_attach_files(tmp_path: Path):
    plan = build_attach_plan(tmp_path, account_id="acct1", token_file="/tmp/oauth_token")
    written = write_attach_files(plan)
    assert tmp_path / ".env.subsurf" in written
    assert (tmp_path / ".env.subsurf").read_text().startswith("SUBSURF_OAUTH_TOKEN_PATH=")
    assert (tmp_path / "subsurf_client_example.py").exists()
    assert (tmp_path / "subsurf_direct_anthropic_example.py").exists()


def test_build_attach_plan_uses_recorded_install_id(tmp_path: Path, monkeypatch):
    install_id_file = tmp_path / "install_id"
    install_id_file.write_text("subsurf-abcd1234")
    monkeypatch.setattr(attach, "DEFAULT_INSTALL_ID_FILE", str(install_id_file))
    monkeypatch.setattr(attach, "DEFAULT_INSTALLS_DIR", str(tmp_path / "installs"))

    plan = build_attach_plan(tmp_path / "app")

    assert plan.token_path == (
        tmp_path / "installs/subsurf-abcd1234/oauth_token_subsurf-abcd1234"
    )
