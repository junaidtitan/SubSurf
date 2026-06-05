"""Interactive wizard for Claude Code OAuth setup and app attachment."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from subsurf.attach import build_attach_plan, print_attach_instructions, write_attach_files


DEFAULT_CONFIG_ROOT = "~/.claude-subsurf"
DEFAULT_TOKEN_FILE = "~/.config/subsurf/oauth_token"
DEFAULT_ACCOUNTS_FILE = "~/.config/subsurf/cc_accounts.json"
DEFAULT_POOL_FILE = "~/.config/subsurf/oauth_pool.json"
DEFAULT_LOG_FILE = "~/.config/subsurf/subsurf_bridge.log"
DEFAULT_PID_FILE = "~/.config/subsurf/subsurf_bridge.pid"


class WizardError(RuntimeError):
    """Recoverable wizard error shown without a Python traceback."""


@dataclass
class WizardOptions:
    account_id: str
    label: str
    config_dir: str
    token_file: str
    accounts_file: str
    pool_file: str
    interval: int
    launch_claude: bool
    skip_login: bool
    start_daemon: bool
    attach_dir: str | None
    overwrite_attach: bool


def prompt(default: str, message: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip()
    return value or default


def prompt_bool(default: bool, message: str) -> bool:
    label = "Y/n" if default else "y/N"
    value = input(f"{message} [{label}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true"}


def heading(title: str) -> None:
    print()
    print(title)
    print("=" * len(title))


def bridge_module():
    from scripts import cc_session_bridge as bridge

    return bridge


def check_prereqs() -> None:
    heading("Prerequisites")
    print(f"Platform: {platform.system()}")
    if platform.system() != "Darwin":
        print("SubSurf's Claude Code Keychain bridge must run on macOS.")
    print(f"Claude CLI: {shutil.which('claude') or 'not found'}")
    print(f"security:   {shutil.which('security') or 'not found'}")


def resolve_options(args: argparse.Namespace) -> WizardOptions:
    account_id = args.account_id or prompt("subsurf1", "Account id")
    label = args.label or prompt(account_id, "Account label/email")
    default_config = str(Path(f"{DEFAULT_CONFIG_ROOT}-{account_id}").expanduser())
    config_dir = args.config_dir or prompt(default_config, "Claude config dir for this login")

    launch_default = bool(shutil.which("claude")) and not args.skip_login
    launch_claude = args.launch_claude
    if launch_claude is None:
        launch_claude = prompt_bool(launch_default, "Launch Claude for login now")

    start_daemon = args.start_daemon
    if start_daemon is None:
        start_daemon = prompt_bool(True, "Start the token keepalive daemon")

    attach_dir = args.attach_dir
    if attach_dir is None and prompt_bool(False, "Attach SubSurf to an app directory now"):
        attach_dir = prompt(".", "App directory")

    return WizardOptions(
        account_id=account_id,
        label=label,
        config_dir=config_dir,
        token_file=args.token_file,
        accounts_file=args.accounts_file,
        pool_file=args.pool_file,
        interval=args.interval,
        launch_claude=launch_claude,
        skip_login=args.skip_login,
        start_daemon=start_daemon,
        attach_dir=attach_dir,
        overwrite_attach=args.overwrite_attach,
    )


def run_claude_login(options: WizardOptions) -> None:
    heading("Claude Login")
    print("A Claude Code session will open with this isolated config directory:")
    print(f"  CLAUDE_CONFIG_DIR={Path(options.config_dir).expanduser()}")
    print()
    print("Inside Claude Code, run `/login`, finish browser auth, then run `/exit`.")
    print("If refresh later fails with invalid_grant, run `/login` again before `/exit`.")
    if options.skip_login:
        print("Skipping launch because --skip-login was provided.")
        input("Press Enter after you have already logged in and exited Claude...")
        return
    if options.launch_claude:
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = str(Path(options.config_dir).expanduser())
        result = subprocess.run(["claude"], env=env)
        if result.returncode != 0:
            raise RuntimeError(f"claude exited with status {result.returncode}")
        return

    print("Run this in another terminal:")
    print(f"  CLAUDE_CONFIG_DIR={Path(options.config_dir).expanduser()} claude")
    input("Press Enter after you have logged in and exited Claude...")


def enroll_and_publish(options: WizardOptions) -> None:
    heading("Enroll And Publish")
    bridge = bridge_module()
    service = bridge.keychain_service_for_config_dir(options.config_dir)
    account = bridge.DEFAULT_ACCOUNT
    prior_accounts = bridge.load_accounts(options.accounts_file)

    enroll_args = argparse.Namespace(
        service=service,
        account=account,
        enroll=options.account_id,
        label=options.label,
        accounts_file=options.accounts_file,
    )
    bridge.enroll_from_keychain(enroll_args)

    tick_args = argparse.Namespace(
        service=service,
        account=account,
        token_file=options.token_file,
        pool_file=options.pool_file,
        accounts_file=options.accounts_file,
        skew=600,
        force_refresh=False,
        push=False,
    )
    try:
        bridge.tick(tick_args)
    except RuntimeError as exc:
        bridge.save_accounts(options.accounts_file, prior_accounts)
        if "invalid_grant" in str(exc):
            raise WizardError(
                "Claude Code's saved refresh token is invalid.\n\n"
                "Recovery:\n"
                f"  1. Re-run this wizard for account `{options.account_id}`.\n"
                "  2. When Claude Code opens, run `/login` and complete browser auth.\n"
                "  3. Then run `/exit` and let the wizard continue.\n\n"
                "The broken enrollment was rolled back; no token was published from "
                "that invalid refresh token.",
            ) from exc
        raise

    token_path = Path(f"{options.token_file}_{options.account_id}").expanduser()
    print(f"Token file ready: {token_path}")


def daemon_command(options: WizardOptions) -> list[str]:
    bridge = bridge_module()
    script = Path(bridge.__file__).resolve()
    return [
        sys.executable,
        str(script),
        "--interval",
        str(options.interval),
        "--token-file",
        options.token_file,
        "--accounts-file",
        options.accounts_file,
        "--pool-file",
        options.pool_file,
    ]


def start_daemon(options: WizardOptions) -> int | None:
    heading("Keepalive")
    command = daemon_command(options)
    print("Keepalive command:")
    print("  " + " ".join(command))

    if not options.start_daemon:
        print("Daemon not started. Run the command above when you want keepalive.")
        return None

    log_file = Path(DEFAULT_LOG_FILE).expanduser()
    pid_file = Path(DEFAULT_PID_FILE).expanduser()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_file.open("ab")
    proc = subprocess.Popen(
        command,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()
    pid_file.write_text(str(proc.pid))
    print(f"Started keepalive pid={proc.pid}")
    print(f"Log: {log_file}")
    print(f"Pid: {pid_file}")
    return proc.pid


def attach_app(options: WizardOptions) -> None:
    heading("Attach")
    token_path = Path(f"{options.token_file}_{options.account_id}").expanduser()
    if not options.attach_dir:
        plan = build_attach_plan(
            ".",
            account_id=options.account_id,
            token_file=options.token_file,
            write_examples=True,
        )
        print_attach_instructions(plan)
        return

    plan = build_attach_plan(
        options.attach_dir,
        account_id=options.account_id,
        token_file=options.token_file,
        write_examples=True,
    )
    print(f"Using token file: {token_path}")
    written = write_attach_files(plan, overwrite=options.overwrite_attach)
    for path in written:
        print(f"wrote {path}")
    print_attach_instructions(plan)


def run_wizard(args: argparse.Namespace) -> int:
    try:
        heading("SubSurf Setup Wizard")
        print("This walks through Claude login, token publishing, keepalive, and app attachment.")
        check_prereqs()
        options = resolve_options(args)
        run_claude_login(options)
        enroll_and_publish(options)
        start_daemon(options)
        attach_app(options)
        heading("Done")
        print(
            "SubSurf is ready. Your app should read SUBSURF_OAUTH_TOKEN_PATH "
            "and keep the daemon running.",
        )
        return 0
    except WizardError as exc:
        heading("Setup Needs Attention")
        print(str(exc))
        return 2


def status(args: argparse.Namespace) -> int:
    heading("SubSurf Status")
    token = Path(args.token_file).expanduser()
    accounts = Path(args.accounts_file).expanduser()
    pid = Path(DEFAULT_PID_FILE).expanduser()
    print(f"Base token:    {token} {'exists' if token.exists() else 'missing'}")
    print(f"Accounts file: {accounts} {'exists' if accounts.exists() else 'missing'}")
    print(f"Daemon pid:    {pid.read_text().strip() if pid.exists() else 'not recorded'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive SubSurf setup wizard")
    parser.add_argument("--account-id")
    parser.add_argument("--label")
    parser.add_argument("--config-dir")
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--accounts-file", default=DEFAULT_ACCOUNTS_FILE)
    parser.add_argument("--pool-file", default=DEFAULT_POOL_FILE)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--skip-login", action="store_true")
    parser.add_argument("--launch-claude", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--start-daemon", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--attach-dir")
    parser.add_argument("--overwrite-attach", action="store_true")
    parser.add_argument("--status", action="store_true", help="show token/daemon status and exit")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.status:
        return status(args)
    return run_wizard(args)


if __name__ == "__main__":
    raise SystemExit(main())
