from __future__ import annotations

import json
import time
from pathlib import Path

from subsurf.throttle import (
    ThrottleSignal,
    check_api_key_fallback_grant,
    clear_throttle_flag,
    consume_fallback_grant,
    read_throttle_flag,
    request_api_key_fallback,
    write_throttle_flag,
)


def test_throttle_flag_roundtrip(tmp_path: Path):
    flag = tmp_path / "throttled.flag"
    write_throttle_flag(flag, ThrottleSignal("rate_limit", 30.0, "429"))
    payload = read_throttle_flag(flag)
    assert payload is not None
    assert payload["kind"] == "rate_limit"
    assert payload["retry_after_s"] == 30.0
    assert "detected_at" in payload


def test_clear_throttle_flag(tmp_path: Path):
    flag = tmp_path / "throttled.flag"
    write_throttle_flag(flag, ThrottleSignal("usage_limit", None, "quota"))
    clear_throttle_flag(flag)
    assert read_throttle_flag(flag) is None


def test_fallback_grant_active_and_consumed(tmp_path: Path):
    grant = tmp_path / "fallback_grant.json"
    grant.write_text(json.dumps({
        "granted_at": time.time(),
        "expires_at": time.time() + 600,
        "max_uses": 3,
        "uses_remaining": 3,
    }))
    assert check_api_key_fallback_grant(grant) is not None
    consume_fallback_grant(grant)
    data = json.loads(grant.read_text())
    assert data["uses_remaining"] == 2


def test_fallback_grant_expired(tmp_path: Path):
    grant = tmp_path / "fallback_grant.json"
    grant.write_text(json.dumps({
        "granted_at": time.time() - 7200,
        "expires_at": time.time() - 3600,
        "max_uses": 3,
        "uses_remaining": 3,
    }))
    assert check_api_key_fallback_grant(grant) is None


def test_fallback_request(tmp_path: Path):
    request = tmp_path / "fallback_request.json"
    request_api_key_fallback(request, "usage_limit hit", vm_id="vm0")
    payload = json.loads(request.read_text())
    assert payload["vm_id"] == "vm0"
    assert payload["reason"] == "usage_limit hit"
