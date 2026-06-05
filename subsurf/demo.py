"""One-command live demo for SubSurf OAuth piggybacking."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from subsurf.attach import build_attach_plan, write_attach_files
from subsurf.config import SubSurfSettings
from subsurf import wizard
from subsurf.wizard import DEFAULT_ACCOUNTS_FILE, DEFAULT_POOL_FILE, DEFAULT_TOKEN_FILE


DEFAULT_APP_DIR = "sample-app"
DEFAULT_PROMPT = "Reply with exactly: subsurf-demo-ok"


@dataclass(frozen=True)
class DemoPaths:
    token_base: Path
    token_path: Path
    accounts_file: Path
    pool_file: Path
    app_dir: Path
    account_id: str | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a foolproof local SubSurf live test without curl quoting",
    )
    parser.add_argument("--account-id", help="account id, e.g. subsurf-4f1a2b3c")
    parser.add_argument("--app-dir", default=DEFAULT_APP_DIR)
    parser.add_argument("--token-file")
    parser.add_argument("--accounts-file")
    parser.add_argument("--pool-file")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--skip-refresh", action="store_true")
    parser.add_argument("--skip-gateway", action="store_true")
    parser.add_argument("--no-sample-app", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="show underlying debug output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print("SubSurf live demo")
    print("=================")

    paths = resolve_demo_paths(args)
    print(f"Account:    {paths.account_id or '(base token)'}")
    print(f"Token file: {paths.token_path}")
    print(f"Sample app: {paths.app_dir}")
    print()

    if not args.skip_refresh:
        refresh_ok = publish_once(paths)
        if not refresh_ok and not token_ready(paths.token_path):
            print_missing_setup_help(paths)
            return 2

    if not token_ready(paths.token_path):
        print_missing_setup_help(paths)
        return 2

    if not args.no_sample_app:
        write_sample_app(paths)

    if not run_python_piggyback(
        paths,
        model=args.model,
        prompt=args.prompt,
        verbose=args.verbose,
    ):
        return 1

    if not args.skip_gateway and not run_gateway_piggyback(
        paths,
        model=args.model,
        prompt=args.prompt,
        verbose=args.verbose,
    ):
        return 1

    print()
    print("Done. SubSurf is working.")
    print()
    print("Next time, just run:")
    print("  python -m subsurf.demo")
    print()
    print("Keepalive status:")
    print("  python -m subsurf.wizard --status")
    return 0


def resolve_demo_paths(args: argparse.Namespace) -> DemoPaths:
    custom_paths = bool(args.token_file or args.accounts_file or args.pool_file)
    account_id = args.account_id
    if account_id is None and not custom_paths:
        account_id = wizard.load_existing_install_id()
    token_file = args.token_file
    accounts_file_arg = args.accounts_file
    pool_file = args.pool_file
    if account_id:
        token_file = token_file or wizard.default_token_file_for_account(account_id)
        accounts_file_arg = accounts_file_arg or wizard.default_accounts_file_for_account(account_id)
        pool_file = pool_file or wizard.default_pool_file_for_account(account_id)
    else:
        token_file = token_file or DEFAULT_TOKEN_FILE
        accounts_file_arg = accounts_file_arg or DEFAULT_ACCOUNTS_FILE
        pool_file = pool_file or DEFAULT_POOL_FILE

    token_base = Path(token_file).expanduser()
    accounts_file = Path(accounts_file_arg).expanduser()
    account_id = account_id or first_account_id(accounts_file)

    token_path = token_base
    if account_id:
        account_token = Path(f"{token_base}_{account_id}").expanduser()
        if account_token.exists() or not token_base.exists():
            token_path = account_token

    if os.environ.get("SUBSURF_OAUTH_TOKEN_PATH"):
        token_path = Path(os.environ["SUBSURF_OAUTH_TOKEN_PATH"]).expanduser()

    return DemoPaths(
        token_base=token_base,
        token_path=token_path,
        accounts_file=accounts_file,
        pool_file=Path(pool_file).expanduser(),
        app_dir=Path(args.app_dir).expanduser().resolve(),
        account_id=account_id,
    )


def first_account_id(accounts_file: Path) -> str | None:
    if not accounts_file.exists():
        return None
    try:
        data = json.loads(accounts_file.read_text())
    except json.JSONDecodeError:
        return None
    accounts = data.get("accounts", [])
    if not accounts:
        return None
    account_id = accounts[0].get("id")
    return str(account_id) if account_id else None


def publish_once(paths: DemoPaths) -> bool:
    print("1. Refresh/publish token")
    print("------------------------")
    from scripts import cc_session_bridge as bridge

    cmd = [
        sys.executable,
        str(Path(bridge.__file__).resolve()),
        "--once",
        "--accounts-file",
        str(paths.accounts_file),
        "--token-file",
        str(paths.token_base),
        "--pool-file",
        str(paths.pool_file),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print("Could not refresh/publish through the bridge.")
        if result.stderr.strip():
            print(result.stderr.strip())
        return False
    print("OK: token published")
    print()
    return True


def token_ready(token_path: Path) -> bool:
    return token_path.exists() and bool(token_path.read_text().strip())


def write_sample_app(paths: DemoPaths) -> None:
    print("2. Write stable sample app")
    print("--------------------------")
    plan = build_attach_plan(
        paths.app_dir,
        account_id=paths.account_id,
        token_file=str(paths.token_base),
        write_examples=True,
    )
    written = write_attach_files(plan, overwrite=True)
    for path in written:
        print(f"wrote {path}")
    print("OK: sample app ready")
    print()


def run_python_piggyback(
    paths: DemoPaths,
    *,
    model: str,
    prompt: str,
    verbose: bool = False,
) -> bool:
    print("3. Python piggyback call")
    print("------------------------")
    try:
        with quiet_output(verbose):
            text = asyncio.run(_complete_with_engine(paths, model=model, prompt=prompt))
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return False

    print(f"model:  {model}")
    print(f"reply:  {text.strip()}")
    print("OK: Python app can piggyback")
    print()
    return True


async def _complete_with_engine(paths: DemoPaths, *, model: str, prompt: str) -> str:
    from subsurf.engine import SubSurfEngine

    settings = SubSurfSettings(
        reasoning_model=model,
        oauth_token_path=str(paths.token_path),
        max_tokens=64,
        temperature=0.0,
    )
    return await SubSurfEngine(settings=settings).complete(
        [{"role": "user", "content": prompt}],
        model=model,
    )


def run_gateway_piggyback(
    paths: DemoPaths,
    *,
    model: str,
    prompt: str,
    verbose: bool = False,
) -> bool:
    print("4. Gateway piggyback call")
    print("-------------------------")
    try:
        with quiet_output(verbose):
            payload = _gateway_completion(paths, model=model, prompt=prompt)
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        print("Tip: install gateway deps with `python -m pip install -e '.[gateway]'`.")
        return False

    print("status: ok")
    print(f"model:  {payload.get('model')}")
    print(f"reply:  {payload['choices'][0]['message']['content'].strip()}")
    print("OK: local gateway can piggyback")
    print()
    return True


def _gateway_completion(paths: DemoPaths, *, model: str, prompt: str) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from subsurf.gateway import create_app

    settings = SubSurfSettings(
        reasoning_model=model,
        oauth_token_path=str(paths.token_path),
        max_tokens=64,
        temperature=0.0,
    )
    response = TestClient(create_app(settings=settings)).post(
        "/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 64,
            "temperature": 0,
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"gateway HTTP {response.status_code}: {response.text}")
    return response.json()


@contextmanager
def quiet_output(verbose: bool):
    if verbose:
        yield
        return
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        yield


def print_missing_setup_help(paths: DemoPaths) -> None:
    print()
    print("SubSurf does not have a usable token yet.")
    print()
    print("Run setup once, complete Claude login, then rerun this demo:")
    print("  python -m subsurf.setup")
    print()
    print("Terminal-only setup:")
    print(f"  python -m subsurf.wizard --attach-dir {paths.app_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
