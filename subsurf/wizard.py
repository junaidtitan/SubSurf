"""Interactive wizard for Claude Code OAuth setup and app attachment."""

from __future__ import annotations

import argparse
import os
import platform
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from subsurf.attach import build_attach_plan, print_attach_instructions, write_attach_files


DEFAULT_CONFIG_ROOT = "~/.claude-subsurf"
DEFAULT_STATE_ROOT = "~/.config/subsurf"
DEFAULT_INSTALLS_DIR = f"{DEFAULT_STATE_ROOT}/installs"
DEFAULT_INSTALL_ID_FILE = "~/.config/subsurf/install_id"
DEFAULT_ATTACH_DIR = "sample-app"
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
    allow_shared_claude_config: bool


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


def load_or_create_install_id(path: str | Path = DEFAULT_INSTALL_ID_FILE) -> str:
    install_id_path = Path(path).expanduser()
    existing = load_existing_install_id(install_id_path)
    if existing:
        return existing

    install_id_path.parent.mkdir(parents=True, exist_ok=True)
    value = f"subsurf-{secrets.token_hex(4)}"
    install_id_path.write_text(value)
    os.chmod(install_id_path, 0o600)
    return value


def load_existing_install_id(path: str | Path = DEFAULT_INSTALL_ID_FILE) -> str | None:
    install_id_path = Path(path).expanduser()
    if not install_id_path.exists():
        return None
    value = install_id_path.read_text().strip()
    return value or None


def default_config_dir_for_account(account_id: str) -> str:
    return str(Path(f"{DEFAULT_CONFIG_ROOT}-{account_id}").expanduser())


def default_state_dir_for_account(account_id: str) -> Path:
    return Path(DEFAULT_INSTALLS_DIR).expanduser() / account_id


def default_token_file_for_account(account_id: str) -> str:
    return str(default_state_dir_for_account(account_id) / "oauth_token")


def default_accounts_file_for_account(account_id: str) -> str:
    return str(default_state_dir_for_account(account_id) / "cc_accounts.json")


def default_pool_file_for_account(account_id: str) -> str:
    return str(default_state_dir_for_account(account_id) / "oauth_pool.json")


def resolve_options(args: argparse.Namespace) -> WizardOptions:
    if args.account_id:
        account_id = args.account_id
    else:
        generated_account_id = load_or_create_install_id(args.install_id_file)
        account_id = prompt(generated_account_id, "Account id") if args.manual else generated_account_id
    label = args.label or (prompt(account_id, "Account label/email") if args.manual else account_id)
    default_config = default_config_dir_for_account(account_id)
    config_dir = args.config_dir or (
        prompt(default_config, "Claude config dir for this login") if args.manual else default_config
    )
    validate_config_dir(
        account_id=account_id,
        config_dir=config_dir,
        allow_shared=args.allow_shared_claude_config,
    )

    if args.skip_login:
        launch_claude = False
    else:
        launch_default = bool(shutil.which("claude"))
        launch_claude = args.launch_claude
        if launch_claude is None:
            launch_claude = (
                prompt_bool(launch_default, "Launch Claude for login now")
                if args.manual
                else launch_default
            )

    start_daemon = args.start_daemon
    if start_daemon is None:
        start_daemon = (
            prompt_bool(True, "Start the token keepalive daemon")
            if args.manual
            else True
        )

    attach_dir = args.attach_dir
    if attach_dir is None:
        if args.manual:
            attach_dir = prompt(".", "App directory") if prompt_bool(True, "Write sample app now") else None
        else:
            attach_dir = DEFAULT_ATTACH_DIR

    overwrite_attach = args.overwrite_attach
    if overwrite_attach is None:
        overwrite_attach = not args.manual

    return WizardOptions(
        account_id=account_id,
        label=label,
        config_dir=config_dir,
        token_file=args.token_file or default_token_file_for_account(account_id),
        accounts_file=args.accounts_file or default_accounts_file_for_account(account_id),
        pool_file=args.pool_file or default_pool_file_for_account(account_id),
        interval=args.interval,
        launch_claude=launch_claude,
        skip_login=args.skip_login,
        start_daemon=start_daemon,
        attach_dir=attach_dir,
        overwrite_attach=overwrite_attach,
        allow_shared_claude_config=args.allow_shared_claude_config,
    )


def is_shared_claude_config(config_dir: str) -> bool:
    return Path(config_dir).expanduser() == Path("~/.claude").expanduser()


def validate_options(options: WizardOptions) -> None:
    validate_config_dir(
        account_id=options.account_id,
        config_dir=options.config_dir,
        allow_shared=options.allow_shared_claude_config,
    )


def validate_config_dir(*, account_id: str, config_dir: str, allow_shared: bool) -> None:
    if not is_shared_claude_config(config_dir) or allow_shared:
        return
    isolated = Path(f"{DEFAULT_CONFIG_ROOT}-{account_id}").expanduser()
    raise WizardError(
        "Refusing to use the shared Claude Code config directory `~/.claude`.\n\n"
        "SubSurf should use an isolated Claude config directory so OAuth "
        "Keychain entries do not collide with your normal Claude Code session.\n\n"
        "Use this instead:\n"
        f"  --config-dir {isolated}\n\n"
        "Only override this guard if you intentionally want to share the "
        "normal Claude Code session:\n"
        "  --allow-shared-claude-config",
    )


def run_claude_login(options: WizardOptions) -> None:
    validate_options(options)
    heading("Claude Login")
    print("A Claude Code session will open with this isolated config directory:")
    print(f"  CLAUDE_CONFIG_DIR={Path(options.config_dir).expanduser()}")
    print()
    print("Safety: do not run `/login` from your normal Claude Code terminal.")
    print("Inside Claude Code, run `/login`, finish browser auth, then run `/exit`.")
    print("If refresh later fails with invalid_grant, run `/login` again before `/exit`.")
    if options.skip_login:
        print("Skipping launch because --skip-login was provided.")
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


def print_configuration(options: WizardOptions) -> None:
    heading("Configuration")
    print(f"Account id:        {options.account_id}")
    print(f"Claude config dir: {Path(options.config_dir).expanduser()}")
    print(f"Token file:        {Path(f'{options.token_file}_{options.account_id}').expanduser()}")
    print(f"Sample app:        {Path(options.attach_dir).expanduser() if options.attach_dir else 'not written'}")
    print(f"Keepalive daemon:  {'start' if options.start_daemon else 'not started'}")


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
        config_dir=options.config_dir,
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


def runtime_file_for_options(options: WizardOptions, name: str, fallback: str) -> Path:
    accounts_file = Path(options.accounts_file).expanduser()
    default_accounts = Path(DEFAULT_ACCOUNTS_FILE).expanduser()
    if accounts_file != default_accounts:
        return accounts_file.parent / name
    return Path(fallback).expanduser()


def start_daemon(options: WizardOptions) -> int | None:
    heading("Keepalive")
    command = daemon_command(options)
    print("Keepalive command:")
    print("  " + " ".join(command))

    if not options.start_daemon:
        print("Daemon not started. Run the command above when you want keepalive.")
        return None

    log_file = runtime_file_for_options(options, "subsurf_bridge.log", DEFAULT_LOG_FILE)
    pid_file = runtime_file_for_options(options, "subsurf_bridge.pid", DEFAULT_PID_FILE)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    existing_pid = running_pid_from_file(pid_file)
    if existing_pid is not None:
        print(f"Keepalive already running pid={existing_pid}")
        print(f"Log: {log_file}")
        print(f"Pid: {pid_file}")
        return existing_pid

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


def running_pid_from_file(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid
    return pid


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
        validate_options(options)
        print_configuration(options)
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
    account_id = getattr(args, "account_id", None) or load_existing_install_id(
        getattr(args, "install_id_file", DEFAULT_INSTALL_ID_FILE),
    )
    if account_id:
        token_file = getattr(args, "token_file", None) or default_token_file_for_account(account_id)
        accounts_file = getattr(args, "accounts_file", None) or default_accounts_file_for_account(
            account_id,
        )
        config_dir = getattr(args, "config_dir", None) or default_config_dir_for_account(account_id)
    else:
        token_file = getattr(args, "token_file", None) or DEFAULT_TOKEN_FILE
        accounts_file = getattr(args, "accounts_file", None) or DEFAULT_ACCOUNTS_FILE
        config_dir = getattr(args, "config_dir", None) or "(unknown)"

    token = Path(token_file).expanduser()
    accounts = Path(accounts_file).expanduser()
    pid = accounts.parent / "subsurf_bridge.pid" if account_id else Path(DEFAULT_PID_FILE).expanduser()
    print(f"Base token:    {token} {'exists' if token.exists() else 'missing'}")
    print(f"Accounts file: {accounts} {'exists' if accounts.exists() else 'missing'}")
    print(f"Account id:    {account_id or 'not recorded'}")
    print(f"Claude config: {Path(config_dir).expanduser() if account_id else config_dir}")
    if account_id:
        service = bridge_module().keychain_service_for_config_dir(config_dir)
        print(f"Keychain svc:  {service}")
    print(f"Daemon pid:    {pid.read_text().strip() if pid.exists() else 'not recorded'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SubSurf setup wizard")
    parser.add_argument("--account-id")
    parser.add_argument("--label")
    parser.add_argument("--config-dir")
    parser.add_argument("--install-id-file", default=DEFAULT_INSTALL_ID_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--manual", action="store_true", help="ask setup questions interactively")
    parser.add_argument("--token-file")
    parser.add_argument("--accounts-file")
    parser.add_argument("--pool-file")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--skip-login", action="store_true")
    parser.add_argument(
        "--allow-shared-claude-config",
        action="store_true",
        help="allow --config-dir ~/.claude instead of an isolated SubSurf config",
    )
    parser.add_argument("--launch-claude", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--start-daemon", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--attach-dir")
    parser.add_argument("--overwrite-attach", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--status", action="store_true", help="show token/daemon status and exit")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.status:
        return status(args)
    return run_wizard(args)


if __name__ == "__main__":
    raise SystemExit(main())
