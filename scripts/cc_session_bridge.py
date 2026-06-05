#!/usr/bin/env python3
"""Claude Code session bridge for SubSurf.

Reads Claude Code OAuth credentials from macOS Keychain, refreshes access
tokens before expiry, and publishes token files consumed by SubSurf's OAuth
client or by VM-side processes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


TOKEN_ENDPOINT = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
KEYCHAIN_SERVICE = "Claude Code-credentials"
DEFAULT_ACCOUNT = os.environ.get("USER", "")
BLOB_KEY = "claudeAiOauth"

DEFAULT_TOKEN_FILE = os.path.expanduser("~/.config/subsurf/oauth_token")
DEFAULT_POOL_FILE = os.path.expanduser("~/.config/subsurf/oauth_pool.json")
DEFAULT_ACCOUNTS_FILE = os.path.expanduser("~/.config/subsurf/cc_accounts.json")
POOL_ENTRY_ID = "cc-session"
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def log(msg: str, **kv: Any) -> None:
    extra = " ".join(f"{k}={v}" for k, v in kv.items())
    ts = time.strftime("%H:%M:%S")
    print(f"[subsurf-bridge {ts}] {msg}{(' ' + extra) if extra else ''}", flush=True)


def keychain_service_for_config_dir(config_dir: str) -> str:
    """Replicate Claude Code's per-CLAUDE_CONFIG_DIR Keychain namespacing."""
    import hashlib

    cd = os.path.expanduser(config_dir)
    if cd == os.path.expanduser("~/.claude"):
        return KEYCHAIN_SERVICE
    h = hashlib.sha256(cd.encode()).hexdigest()[:8]
    return f"{KEYCHAIN_SERVICE}-{h}"


def read_keychain(service: str, account: str) -> dict[str, Any]:
    args = ["security", "find-generic-password", "-s", service]
    if account:
        args += ["-a", account]
    args += ["-w"]
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(
            f"keychain item not found (service={service!r} account={account!r}). "
            "Is Claude Code logged in on this machine?",
        )
    raw = json.loads(out.stdout)
    blob = raw.get(BLOB_KEY)
    if not isinstance(blob, dict) or "accessToken" not in blob:
        raise RuntimeError(f"unexpected keychain payload shape: keys={list(raw)}")
    return blob


def write_keychain(service: str, account: str, blob: dict[str, Any]) -> None:
    """Write the rotated credential blob back to the macOS Keychain."""
    payload = json.dumps({BLOB_KEY: blob}, separators=(",", ":"))
    esc = payload.replace("\\", "\\\\").replace('"', '\\"')
    cmd = f'add-generic-password -U -a "{account}" -s "{service}" -w "{esc}"\n'
    proc = subprocess.run(["security", "-i"], input=cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"keychain write failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()[:200]}",
        )


def expiring(blob: dict[str, Any], skew_s: int) -> bool:
    exp_ms = int(blob.get("expiresAt", 0))
    return (exp_ms / 1000.0) - time.time() < skew_s


def refresh(blob: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
    """Exchange a refresh token for a new access token."""
    rt = blob.get("refreshToken")
    if not rt:
        raise RuntimeError("no refreshToken in credential blob")
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": CLIENT_ID,
    }).encode()
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "claude-cli/2.1.81 (external, cli)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"refresh HTTP {e.code}: {detail}") from None

    new = dict(blob)
    new["accessToken"] = data["access_token"]
    if data.get("refresh_token"):
        new["refreshToken"] = data["refresh_token"]
    if data.get("expires_in"):
        new["expiresAt"] = int(time.time() * 1000) + int(data["expires_in"]) * 1000
    return new


def atomic_write(path: str, text: str, mode: int = 0o600) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text)
    os.chmod(tmp, mode)
    os.replace(tmp, p)


def publish_local(token: str, token_file: str) -> None:
    atomic_write(token_file, token)


def _load_oauth_pool(pool_file: str):
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    import oauth_pool  # type: ignore

    oauth_pool.POOL_PATH = Path(pool_file).expanduser()
    return oauth_pool


def publish_pool(token: str, pool_file: str) -> int:
    """Update the single-session pool entry and push it to registered VMs."""
    oauth_pool = _load_oauth_pool(pool_file)
    pool = oauth_pool.load_pool()

    entry = next(
        (t for t in pool.get("tokens", []) if t.get("id") == POOL_ENTRY_ID),
        None,
    )
    now = time.time()
    if entry is None:
        entry = {
            "id": POOL_ENTRY_ID,
            "label": "claude-code session",
            "tier": "max",
            "status": "active",
            "added_at": now,
        }
        pool.setdefault("tokens", []).append(entry)
    entry.update(
        token=token,
        last_rotated=now,
        status="active",
        cooldown_until=None,
        last_error=None,
    )
    oauth_pool.save_pool(pool)

    pushed = 0
    for vm in pool.get("vms", {}):
        try:
            oauth_pool._push_token(oauth_pool._ssh_host(pool, vm), token)
            pushed += 1
        except Exception as exc:  # noqa: BLE001
            log("vm_push_failed", vm=vm, err=str(exc)[:80])
    return pushed


def load_accounts(path: str) -> list[dict[str, Any]]:
    p = Path(path).expanduser()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text()).get("accounts", [])
    except Exception:
        return []


def save_accounts(path: str, accounts: list[dict[str, Any]]) -> None:
    atomic_write(path, json.dumps({"accounts": accounts}, indent=2))


def enroll_from_keychain(args: argparse.Namespace) -> int:
    blob = read_keychain(args.service, args.account)
    accounts = [
        a for a in load_accounts(args.accounts_file)
        if a.get("id") != args.enroll
    ]
    accounts.append({
        "id": args.enroll,
        "label": args.label,
        "accessToken": blob["accessToken"],
        "refreshToken": blob.get("refreshToken"),
        "expiresAt": blob.get("expiresAt", 0),
        "scopes": blob.get("scopes"),
        "subscriptionType": blob.get("subscriptionType"),
        "rateLimitTier": blob.get("rateLimitTier"),
    })
    save_accounts(args.accounts_file, accounts)
    log("enrolled", id=args.enroll, label=args.label or "-", total=len(accounts))
    return 0


def remove_account(args: argparse.Namespace) -> int:
    accounts = [
        a for a in load_accounts(args.accounts_file)
        if a.get("id") != args.remove
    ]
    save_accounts(args.accounts_file, accounts)
    token_file = Path(f"{args.token_file}_{args.remove}").expanduser()
    if token_file.exists():
        token_file.unlink()
    log("removed", id=args.remove, remaining=len(accounts))
    return 0


def list_accounts(args: argparse.Namespace) -> int:
    accounts = load_accounts(args.accounts_file)
    if not accounts:
        log("no_accounts", file=args.accounts_file)
        return 0
    for account in accounts:
        exp = int(account.get("expiresAt", 0) / 1000 - time.time())
        print(f"  {account.get('id',''):14s} {account.get('label',''):28s} expires_in={exp}s")
    return 0


def feed_pool_multi(accounts: list[dict[str, Any]], pool_file: str) -> int:
    """Upsert each account into oauth_pool.json and push one per VM."""
    oauth_pool = _load_oauth_pool(pool_file)
    pool = oauth_pool.load_pool()
    tokens = pool.setdefault("tokens", [])
    now = time.time()

    for account in accounts:
        token_id = f"cc-{account['id']}"
        entry = next((t for t in tokens if t.get("id") == token_id), None)
        if entry is None:
            entry = {
                "id": token_id,
                "label": account.get("label", ""),
                "tier": "max",
                "added_at": now,
            }
            tokens.append(entry)
        entry.update(
            token=account["accessToken"],
            last_rotated=now,
            status="active",
            cooldown_until=None,
            last_error=None,
        )
    oauth_pool.save_pool(pool)

    vm_names = list(pool.get("vms", {}).keys())
    ids = [f"cc-{account['id']}" for account in accounts]
    pushed = 0
    for i, vm in enumerate(vm_names):
        if not ids:
            break
        token_id = ids[i % len(ids)]
        token = next((t["token"] for t in tokens if t.get("id") == token_id), None)
        if not token:
            continue
        try:
            oauth_pool._push_token(oauth_pool._ssh_host(pool, vm), token)
            pool["vms"][vm]["token_id"] = token_id
            pushed += 1
        except Exception as exc:  # noqa: BLE001
            log("vm_push_failed", vm=vm, err=str(exc)[:80])
    oauth_pool.save_pool(pool)
    return pushed


def tick(args: argparse.Namespace) -> None:
    accounts = load_accounts(args.accounts_file)
    if accounts:
        tick_multi(args, accounts)
    else:
        tick_single(args)


def tick_multi(args: argparse.Namespace, accounts: list[dict[str, Any]]) -> None:
    refreshed = 0
    for account in accounts:
        if args.force_refresh or expiring(account, args.skew):
            account.update(refresh(account))
            refreshed += 1
    if refreshed:
        save_accounts(args.accounts_file, accounts)

    for account in accounts:
        publish_local(account["accessToken"], f"{args.token_file}_{account['id']}")
    publish_local(accounts[0]["accessToken"], args.token_file)

    note = f"accounts={len(accounts)} refreshed={refreshed}"
    if args.push:
        pushed = feed_pool_multi(accounts, args.pool_file)
        note += f" vms_pushed={pushed}"
    log("multi_published", **dict(kv.split("=", 1) for kv in note.split()))


def tick_single(args: argparse.Namespace) -> None:
    blob = read_keychain(args.service, args.account)
    if args.force_refresh or expiring(blob, args.skew):
        exp_in = int(blob.get("expiresAt", 0) / 1000 - time.time())
        log("refreshing", expires_in_s=exp_in)
        blob = refresh(blob)
        write_keychain(args.service, args.account, blob)
        log(
            "refreshed_and_persisted",
            new_expires_in_s=int(blob["expiresAt"] / 1000 - time.time()),
        )
    token = blob["accessToken"]
    publish_local(token, args.token_file)
    note = f"file={args.token_file}"
    if args.push:
        pushed = publish_pool(token, args.pool_file)
        note += f" pushed_to_vms={pushed}"
    log("published", **dict(kv.split("=", 1) for kv in note.split()))


def selftest() -> int:
    svc = "subsurf_bridge_selftest"
    acct = DEFAULT_ACCOUNT or "selftest"
    sample = {
        "accessToken": 'sk-ant-oat01-"quote"\\back/slash',
        "refreshToken": "sk-ant-ort01-xyz",
        "expiresAt": 1780000000000,
        "scopes": ["a", "b"],
        "subscriptionType": "max",
        "rateLimitTier": "default_x",
    }
    try:
        write_keychain(svc, acct, sample)
        got = read_keychain(svc, acct)
        ok = got == sample
        log("selftest", roundtrip_ok=ok)
        if not ok:
            log("selftest_mismatch", expected=sample, got=got)
        return 0 if ok else 1
    finally:
        subprocess.run(
            ["security", "delete-generic-password", "-s", svc, "-a", acct],
            capture_output=True,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Claude Code session bridge for SubSurf")
    parser.add_argument("--service", default=KEYCHAIN_SERVICE)
    parser.add_argument(
        "--config-dir",
        help="CLAUDE_CONFIG_DIR to read; derives the per-dir Keychain service name",
    )
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--pool-file", default=DEFAULT_POOL_FILE)
    parser.add_argument("--accounts-file", default=DEFAULT_ACCOUNTS_FILE)
    parser.add_argument("--enroll", metavar="ID")
    parser.add_argument("--list-accounts", action="store_true")
    parser.add_argument("--remove", metavar="ID")
    parser.add_argument("--skew", type=int, default=600)
    parser.add_argument("--interval", type=int, default=0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--label", default="")
    parser.add_argument("--selftest", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "config_dir", None):
        args.service = keychain_service_for_config_dir(args.config_dir)
    if args.selftest:
        return selftest()
    if sys.platform != "darwin":
        log("error", reason="bridge must run on the macOS host Keychain source")
        return 2
    if args.list_accounts:
        return list_accounts(args)
    if args.remove:
        return remove_account(args)
    if args.enroll:
        return enroll_from_keychain(args)
    if args.once or args.interval <= 0:
        tick(args)
        return 0
    log("daemon_start", interval=args.interval, skew=args.skew, push=args.push)
    while True:
        try:
            tick(args)
        except Exception as exc:  # noqa: BLE001
            log("tick_error", err=str(exc)[:160])
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
