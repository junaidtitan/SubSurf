#!/usr/bin/env python3
"""OAuth token pool manager for SubSurf.

The host owns `~/.config/subsurf/oauth_pool.json`; each VM/process consumes a
single token file written by this script over SSH.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


POOL_PATH = Path(os.environ.get(
    "SUBSURF_OAUTH_POOL",
    os.path.expanduser("~/.config/subsurf/oauth_pool.json"),
))

REMOTE_TOKEN_PATH = "~/.config/subsurf/oauth_token"
REMOTE_THROTTLE_FLAG = "~/.config/subsurf/throttled.flag"
REMOTE_FALLBACK_GRANT = "~/.config/subsurf/fallback_grant.json"
DEFAULT_COOLDOWN_S = 5 * 60 * 60
SSH_TIMEOUT_S = 30


@dataclass
class Token:
    id: str
    token: str
    label: str = ""
    tier: str = "max-20x"
    assigned_to: str | None = None
    status: str = "active"  # active | cooling | revoked
    last_rotated: float | None = None
    cooldown_until: float | None = None
    last_error: str | None = None
    added_at: float = field(default_factory=time.time)

    def is_available(self) -> bool:
        if self.status != "active":
            return False
        if self.assigned_to is not None:
            return False
        if self.cooldown_until and time.time() < self.cooldown_until:
            return False
        return True

    def as_status_line(self) -> str:
        assigned = self.assigned_to or "-"
        cool = ""
        if self.cooldown_until and time.time() < self.cooldown_until:
            mins = int((self.cooldown_until - time.time()) / 60)
            cool = f" cooling:{mins}m"
        return (
            f"  {self.id:<10} {self.tier:<10} assigned:{assigned:<8} "
            f"status:{self.status}{cool} label:{self.label}"
        )


def empty_pool() -> dict[str, Any]:
    return {
        "tokens": [],
        "vms": {},
        "api_key_fallback": {"keys": [], "last_granted_at": None},
    }


def load_pool() -> dict[str, Any]:
    if not POOL_PATH.exists():
        return empty_pool()
    try:
        data = json.loads(POOL_PATH.read_text())
    except json.JSONDecodeError as exc:
        sys.exit(f"pool file {POOL_PATH} is corrupt: {exc}")
    data.setdefault("tokens", [])
    data.setdefault("vms", {})
    data.setdefault("api_key_fallback", {"keys": [], "last_granted_at": None})
    return data


def save_pool(pool: dict[str, Any]) -> None:
    POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = POOL_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(pool, indent=2))
    tmp.replace(POOL_PATH)
    try:
        os.chmod(POOL_PATH, 0o600)
    except OSError:
        pass


def tokens_from(pool: dict[str, Any]) -> list[Token]:
    return [Token(**t) for t in pool["tokens"]]


def save_tokens(pool: dict[str, Any], tokens: list[Token]) -> None:
    pool["tokens"] = [asdict(t) for t in tokens]


def find_token(tokens: list[Token], token_id: str) -> Token | None:
    return next((t for t in tokens if t.id == token_id), None)


def _ssh_host(pool: dict[str, Any], vm: str) -> str:
    info = pool["vms"].get(vm)
    if not info:
        sys.exit(f"unknown vm {vm!r}. add it first with `add-vm`.")
    return info["host"]


def _push_token(remote_host: str, token: str) -> None:
    """Write token to the remote VM without putting it in argv."""
    remote_dir = os.path.dirname(REMOTE_TOKEN_PATH) or "."
    cmd = [
        "ssh",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT_S}",
        remote_host,
        f"mkdir -p {remote_dir} && cat > {REMOTE_TOKEN_PATH} && chmod 600 {REMOTE_TOKEN_PATH}",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=token.encode(),
            capture_output=True,
            timeout=SSH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        sys.exit(f"ssh push to {remote_host} timed out after {SSH_TIMEOUT_S}s")
    if result.returncode != 0:
        sys.exit(
            f"failed to push token to {remote_host}: "
            f"{result.stderr.decode(errors='replace')}",
        )


def _ssh_read(remote_host: str, remote_path: str) -> str | None:
    cmd = [
        "ssh",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT_S}",
        remote_host,
        f"cat {remote_path} 2>/dev/null || true",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=SSH_TIMEOUT_S)
    if result.returncode != 0:
        return None
    out = result.stdout.decode(errors="replace").strip()
    return out or None


def _ssh_exec(
    remote_host: str,
    command: str,
    timeout_s: int = SSH_TIMEOUT_S,
) -> tuple[int, str, str]:
    result = subprocess.run(
        ["ssh", "-o", f"ConnectTimeout={SSH_TIMEOUT_S}", remote_host, command],
        capture_output=True,
        timeout=timeout_s,
    )
    return (
        result.returncode,
        result.stdout.decode(errors="replace"),
        result.stderr.decode(errors="replace"),
    )


def _ssh_rm(remote_host: str, remote_path: str) -> None:
    try:
        subprocess.run(
            ["ssh", "-o", f"ConnectTimeout={SSH_TIMEOUT_S}", remote_host, f"rm -f {remote_path}"],
            capture_output=True,
            timeout=SSH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        pass


def _push_json(remote_host: str, remote_path: str, payload: dict[str, Any]) -> None:
    remote_dir = os.path.dirname(remote_path) or "."
    cmd = [
        "ssh",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT_S}",
        remote_host,
        f"mkdir -p {remote_dir} && cat > {remote_path} && chmod 600 {remote_path}",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=json.dumps(payload).encode(),
            capture_output=True,
            timeout=SSH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        sys.exit(f"ssh push-json to {remote_host} timed out after {SSH_TIMEOUT_S}s")
    if result.returncode != 0:
        sys.exit(
            f"failed to push json to {remote_host}: "
            f"{result.stderr.decode(errors='replace')}",
        )


def cmd_register(args: argparse.Namespace) -> None:
    pool = load_pool()
    token_list = tokens_from(pool)
    if find_token(token_list, args.id):
        sys.exit(f"token id {args.id!r} already exists. use a different id.")

    secret = args.token if args.token else sys.stdin.read().strip()
    if not secret.startswith("sk-ant-oat"):
        sys.exit(
            "token doesn't look like an OAuth token "
            f"(expected sk-ant-oat..., got {secret[:12]!r}).",
        )

    token_list.append(Token(id=args.id, token=secret, label=args.label, tier=args.tier))
    save_tokens(pool, token_list)
    save_pool(pool)
    print(f"registered token {args.id!r} ({args.tier}, label={args.label!r})")


def cmd_add_vm(args: argparse.Namespace) -> None:
    pool = load_pool()
    pool["vms"][args.vm] = {"host": args.host, "token_id": None}
    save_pool(pool)
    print(f"registered vm {args.vm!r} -> {args.host}")


def cmd_rm_vm(args: argparse.Namespace) -> None:
    pool = load_pool()
    info = pool["vms"].pop(args.vm, None)
    if info and info.get("token_id"):
        token_list = tokens_from(pool)
        token = find_token(token_list, info["token_id"])
        if token:
            token.assigned_to = None
            save_tokens(pool, token_list)
    save_pool(pool)
    print(f"removed vm {args.vm!r}")


def cmd_assign(args: argparse.Namespace) -> None:
    pool = load_pool()
    token_list = tokens_from(pool)
    remote_host = _ssh_host(pool, args.vm)

    current_id = pool["vms"][args.vm].get("token_id")
    if current_id and not args.force:
        sys.exit(
            f"vm {args.vm!r} already has token {current_id!r}. "
            "use --force to rotate, or `recover` to mark it throttled.",
        )

    if args.token_id:
        token = find_token(token_list, args.token_id)
        if token is None:
            sys.exit(f"unknown token id {args.token_id!r}")
        if token.assigned_to and token.assigned_to != args.vm:
            sys.exit(f"token {args.token_id!r} already assigned to {token.assigned_to!r}")
    else:
        available = [token for token in token_list if token.is_available()]
        if not available:
            sys.exit("no reserve tokens available. register more, or wait for cooldowns.")
        token = available[0]

    if current_id:
        old = find_token(token_list, current_id)
        if old:
            old.assigned_to = None

    token.assigned_to = args.vm
    token.last_rotated = time.time()
    pool["vms"][args.vm]["token_id"] = token.id

    _push_token(remote_host, token.token)
    _ssh_rm(remote_host, REMOTE_THROTTLE_FLAG)
    save_tokens(pool, token_list)
    save_pool(pool)
    print(f"assigned {token.id!r} -> {args.vm} ({remote_host})")


def cmd_recover(args: argparse.Namespace) -> None:
    pool = load_pool()
    token_list = tokens_from(pool)
    vm_info = pool["vms"].get(args.vm)
    if not vm_info:
        sys.exit(f"unknown vm {args.vm!r}")

    remote_host = vm_info["host"]
    current_id = vm_info.get("token_id")
    if not current_id:
        sys.exit(f"vm {args.vm!r} has no token assigned; use `assign` instead.")

    current = find_token(token_list, current_id)
    if current is None:
        sys.exit(f"pool is inconsistent: vm {args.vm} claims missing token {current_id!r}")

    flag_raw = _ssh_read(remote_host, REMOTE_THROTTLE_FLAG)
    cooldown_s = DEFAULT_COOLDOWN_S
    err_kind = "unknown"
    if flag_raw:
        try:
            flag = json.loads(flag_raw)
            err_kind = flag.get("kind", "unknown")
            if flag.get("retry_after_s"):
                cooldown_s = max(float(flag["retry_after_s"]), 60)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    current.status = "cooling"
    current.assigned_to = None
    current.cooldown_until = time.time() + cooldown_s
    current.last_error = err_kind
    vm_info["token_id"] = None
    save_tokens(pool, token_list)
    save_pool(pool)
    print(f"marked {current_id!r} cooling ({err_kind}, ~{int(cooldown_s / 60)}m)")

    cmd_assign(argparse.Namespace(vm=args.vm, token_id=None, force=False))


def cmd_status(args: argparse.Namespace) -> None:
    pool = load_pool()
    token_list = tokens_from(pool)
    now = time.time()
    changed = False
    for token in token_list:
        if token.status == "cooling" and token.cooldown_until and now >= token.cooldown_until:
            token.status = "active"
            token.cooldown_until = None
            changed = True
    if changed:
        save_tokens(pool, token_list)
        save_pool(pool)

    reserve = sum(1 for token in token_list if token.status == "active" and not token.assigned_to)
    assigned = sum(1 for token in token_list if token.assigned_to)
    cooling = sum(1 for token in token_list if token.status == "cooling")
    revoked = sum(1 for token in token_list if token.status == "revoked")

    print(f"Pool: {POOL_PATH}")
    print(
        f"  tokens: {len(token_list)}  reserve:{reserve}  "
        f"assigned:{assigned}  cooling:{cooling}  revoked:{revoked}",
    )
    print(f"  api-key fallback: {len(pool['api_key_fallback']['keys'])} keys")
    print()
    print("Tokens:")
    for token in sorted(token_list, key=lambda item: item.id):
        print(token.as_status_line())
    print()
    print("VMs:")
    for vm, info in sorted(pool["vms"].items()):
        token_id = info.get("token_id") or "-"
        print(f"  {vm:<8} host={info['host']:<30} token={token_id}")


def cmd_list(args: argparse.Namespace) -> None:
    pool = load_pool()
    if not args.reveal:
        for token in pool["tokens"]:
            if token.get("token"):
                token["token"] = token["token"][:12] + "...(redacted)"
        pool["api_key_fallback"]["keys"] = [
            key[:12] + "...(redacted)" for key in pool["api_key_fallback"]["keys"]
        ]
    print(json.dumps(pool, indent=2))


def cmd_grant_fallback(args: argparse.Namespace) -> None:
    pool = load_pool()
    remote_host = _ssh_host(pool, args.vm)
    now = time.time()
    grant = {
        "granted_at": now,
        "expires_at": now + args.duration,
        "max_uses": args.max_uses,
        "uses_remaining": args.max_uses,
        "note": args.note,
    }
    _push_json(remote_host, REMOTE_FALLBACK_GRANT, grant)
    pool["api_key_fallback"]["last_granted_at"] = now
    save_pool(pool)
    print(
        f"granted fallback to {args.vm}; expires in {args.duration}s, "
        f"max_uses={args.max_uses}",
    )


def cmd_revoke_fallback(args: argparse.Namespace) -> None:
    pool = load_pool()
    _ssh_rm(_ssh_host(pool, args.vm), REMOTE_FALLBACK_GRANT)
    print(f"revoked fallback grant on {args.vm}")


def cmd_canary(args: argparse.Namespace) -> None:
    pool = load_pool()
    if args.vm:
        targets = {args.vm: pool["vms"][args.vm]} if args.vm in pool["vms"] else {}
        if not targets:
            sys.exit(f"unknown vm {args.vm!r}")
    else:
        targets = pool["vms"]
    if not targets:
        sys.exit("no VMs registered; add some with `add-vm` first.")

    remote_cmd = (
        f"cd {args.remote_dir} && "
        f"{args.python} - <<'PY'\n"
        "import asyncio, json\n"
        "from subsurf.engine import SubSurfEngine\n"
        "async def main():\n"
        "    text = await SubSurfEngine().complete([{'role':'user','content':'reply with subsurf-canary'}])\n"
        "    print(json.dumps({'ok': 'subsurf-canary' in text.lower(), 'text': text[:120]}))\n"
        "asyncio.run(main())\n"
        "PY"
    )
    ssh_timeout = int(args.timeout) + 15
    results: dict[str, dict[str, Any]] = {}
    for vm, info in targets.items():
        try:
            rc, stdout, stderr = _ssh_exec(info["host"], remote_cmd, timeout_s=ssh_timeout)
        except subprocess.TimeoutExpired:
            results[vm] = {"ok": False, "error": f"ssh timeout after {ssh_timeout}s"}
            continue
        results[vm] = parse_canary_output(stdout, stderr, rc)

    any_failed = False
    width = max((len(vm) for vm in results), default=4)
    for vm, result in results.items():
        ok = bool(result.get("ok"))
        any_failed = any_failed or not ok
        detail = "" if ok else f"  error={result.get('error', 'unknown')}"
        print(f"{'OK  ' if ok else 'FAIL'}  {vm:<{width}}{detail}")
    if args.json:
        print(json.dumps(results, indent=2))
    if any_failed:
        sys.exit(1)


def parse_canary_output(stdout: str, stderr: str, rc: int) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            continue
    return {
        "ok": False,
        "error": f"canary produced no JSON (rc={rc}). stderr tail: {stderr.strip()[-300:]!r}",
    }


def cmd_watch(args: argparse.Namespace) -> None:
    pool = load_pool()
    print(f"watching {len(pool['vms'])} VMs every {args.interval}s (pool={POOL_PATH})")
    while True:
        pool = load_pool()
        for vm, info in pool["vms"].items():
            try:
                flag_raw = _ssh_read(info["host"], REMOTE_THROTTLE_FLAG)
            except subprocess.TimeoutExpired:
                print(f"[{ts()}] {vm}: ssh timeout", flush=True)
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"[{ts()}] {vm}: ssh error: {exc}", flush=True)
                continue
            if not flag_raw:
                continue
            try:
                flag = json.loads(flag_raw)
            except json.JSONDecodeError:
                flag = {"kind": "unknown"}
            print(f"[{ts()}] {vm}: throttled ({flag.get('kind')}); recovering", flush=True)
            try:
                cmd_recover(argparse.Namespace(vm=vm))
            except SystemExit as exc:
                print(f"[{ts()}] {vm}: recover failed: {exc}", flush=True)
            except subprocess.TimeoutExpired:
                print(f"[{ts()}] {vm}: recover timed out", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[{ts()}] {vm}: recover error: {exc}", flush=True)
        time.sleep(args.interval)


def ts() -> str:
    return time.strftime("%H:%M:%S")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    register = sub.add_parser("register", help="add a new OAuth token")
    register.add_argument("--id", required=True)
    register.add_argument("--label", default="")
    register.add_argument("--tier", default="max-20x")
    register.add_argument("--token")
    register.set_defaults(func=cmd_register)

    add_vm = sub.add_parser("add-vm", help="register a VM ssh target")
    add_vm.add_argument("--vm", required=True)
    add_vm.add_argument("--host", required=True)
    add_vm.set_defaults(func=cmd_add_vm)

    rm_vm = sub.add_parser("rm-vm", help="deregister a VM")
    rm_vm.add_argument("--vm", required=True)
    rm_vm.set_defaults(func=cmd_rm_vm)

    assign = sub.add_parser("assign", help="pin a token to a VM and push it")
    assign.add_argument("--vm", required=True)
    assign.add_argument("--token-id")
    assign.add_argument("--force", action="store_true")
    assign.set_defaults(func=cmd_assign)

    recover = sub.add_parser("recover", help="rotate throttled VM to reserve token")
    recover.add_argument("--vm", required=True)
    recover.set_defaults(func=cmd_recover)

    sub.add_parser("status", help="human-readable pool status").set_defaults(func=cmd_status)

    list_cmd = sub.add_parser("list", help="machine-readable pool dump")
    list_cmd.add_argument("--reveal", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    grant = sub.add_parser("grant-fallback", help="allow API-key fallback on a VM")
    grant.add_argument("--vm", required=True)
    grant.add_argument("--duration", type=int, default=1800)
    grant.add_argument("--max-uses", type=int, default=20)
    grant.add_argument("--note", default=None)
    grant.set_defaults(func=cmd_grant_fallback)

    revoke = sub.add_parser("revoke-fallback", help="revoke a VM fallback grant")
    revoke.add_argument("--vm", required=True)
    revoke.set_defaults(func=cmd_revoke_fallback)

    watch = sub.add_parser("watch", help="daemon: auto-recover throttled VMs")
    watch.add_argument("--interval", type=float, default=15.0)
    watch.set_defaults(func=cmd_watch)

    canary = sub.add_parser("canary", help="run a minimal SubSurf round-trip on VMs")
    canary.add_argument("--vm")
    canary.add_argument("--timeout", type=float, default=60.0)
    canary.add_argument("--python", default="python3")
    canary.add_argument("--remote-dir", default="~/subsurf")
    canary.add_argument("--json", action="store_true")
    canary.set_defaults(func=cmd_canary)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
