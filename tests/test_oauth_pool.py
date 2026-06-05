from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import oauth_pool  # noqa: E402


@pytest.fixture
def pool_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "oauth_pool.json"
    monkeypatch.setattr(oauth_pool, "POOL_PATH", path)
    return path


@pytest.fixture
def no_ssh(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def fake_push_token(host, token):
        calls.append(("push_token", host, token))

    def fake_push_json(host, path, payload):
        calls.append(("push_json", host, path, payload))

    def fake_ssh_read(host, path):
        return None

    def fake_ssh_rm(host, path):
        calls.append(("rm", host, path))

    monkeypatch.setattr(oauth_pool, "_push_token", fake_push_token)
    monkeypatch.setattr(oauth_pool, "_push_json", fake_push_json)
    monkeypatch.setattr(oauth_pool, "_ssh_read", fake_ssh_read)
    monkeypatch.setattr(oauth_pool, "_ssh_rm", fake_ssh_rm)
    return calls


def run_pool(*args: str) -> None:
    oauth_pool.main(list(args))


def test_register_valid_token(pool_path: Path):
    run_pool("register", "--id", "acct1", "--token", "sk-ant-oat01-abc")
    data = json.loads(pool_path.read_text())
    assert data["tokens"][0]["id"] == "acct1"


def test_register_rejects_api_key(pool_path: Path):
    with pytest.raises(SystemExit):
        run_pool("register", "--id", "acct1", "--token", "sk-ant-api03-abc")


def test_assign_picks_first_available(pool_path: Path, no_ssh):
    run_pool("register", "--id", "acct1", "--token", "sk-ant-oat01-a")
    run_pool("register", "--id", "acct2", "--token", "sk-ant-oat01-b")
    run_pool("add-vm", "--vm", "vm0", "--host", "ubuntu@10.0.0.1")
    run_pool("assign", "--vm", "vm0")

    data = json.loads(pool_path.read_text())
    assert data["vms"]["vm0"]["token_id"] == "acct1"
    assert any(call[0] == "push_token" for call in no_ssh)


def test_recover_cools_current_and_assigns_reserve(pool_path: Path, no_ssh, monkeypatch):
    run_pool("register", "--id", "acct1", "--token", "sk-ant-oat01-a")
    run_pool("register", "--id", "acct2", "--token", "sk-ant-oat01-b")
    run_pool("add-vm", "--vm", "vm0", "--host", "ubuntu@10.0.0.1")
    run_pool("assign", "--vm", "vm0")

    monkeypatch.setattr(
        oauth_pool,
        "_ssh_read",
        lambda h, p: json.dumps({"kind": "rate_limit", "retry_after_s": 120}),
    )
    run_pool("recover", "--vm", "vm0")

    data = json.loads(pool_path.read_text())
    tokens = {token["id"]: token for token in data["tokens"]}
    assert tokens["acct1"]["status"] == "cooling"
    assert tokens["acct1"]["cooldown_until"] > time.time()
    assert data["vms"]["vm0"]["token_id"] == "acct2"


def test_grant_fallback_writes_json(pool_path: Path, no_ssh):
    run_pool("add-vm", "--vm", "vm0", "--host", "ubuntu@10.0.0.1")
    run_pool("grant-fallback", "--vm", "vm0", "--duration", "600", "--max-uses", "10")
    grants = [call for call in no_ssh if call[0] == "push_json"]
    assert grants
    assert grants[0][3]["uses_remaining"] == 10


def test_list_redacts_by_default(pool_path: Path, capsys):
    run_pool("register", "--id", "acct1", "--token", "sk-ant-oat01-secret")
    run_pool("list")
    out = capsys.readouterr().out
    assert "secret" not in out
    assert "redacted" in out
