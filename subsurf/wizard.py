"""Interactive wizard for Claude Code OAuth setup and app attachment."""

from __future__ import annotations

import argparse
import os
import platform
import secrets
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from subsurf import codex_auth
from subsurf.attach import build_attach_plan, print_attach_instructions, write_attach_files
from subsurf.openai_models import DEFAULT_CODEX_MODEL, choose_available_model, resolve_model_id


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


class WizardCancelled(WizardError):
    """Raised when the user exits the cleared-screen wizard before setup starts."""


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


@dataclass(frozen=True)
class ProviderChoice:
    provider: str
    title: str
    detail: str


PROVIDER_CHOICES = (
    ProviderChoice(
        provider="claude",
        title="Claude Code subscription",
        detail="Use an isolated Claude Code OAuth login, keep it alive, and attach apps to it.",
    ),
    ProviderChoice(
        provider="codex",
        title="Codex subscription",
        detail="Use an isolated Codex login/CODEX_HOME and attach apps to that session.",
    ),
)

SUBSURF_LOGO = (
    "  ____        _     ____             __",
    " / ___| _   _| |__ / ___| _   _ _ __/ _|",
    " \\___ \\| | | | '_ \\\\___ \\| | | | '__| |_",
    "  ___) | |_| | |_) |___) | |_| | |  |  _|",
    " |____/ \\__,_|_.__/|____/ \\__,_|_|  |_|",
)

ANSI_RESET = "\033[0m"
ANSI_CYAN = "\033[96m"
ANSI_GREEN = "\033[92m"
ANSI_PURPLE = "\033[95m"
ANSI_WHITE = "\033[97m"
ANSI_DIM = "\033[90m"


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


def prompt_provider(default: str = "claude") -> str:
    value = input(f"Provider: claude or codex [{default}]: ").strip().lower()
    provider = value or default
    if provider not in {"claude", "codex"}:
        raise WizardError("Provider must be `claude` or `codex`.")
    return provider


def heading(title: str) -> None:
    print()
    print(title)
    print("=" * len(title))


def paint(code: str, text: str) -> str:
    if os.environ.get("NO_COLOR"):
        return text
    return f"{code}{text}{ANSI_RESET}"


def should_launch_clear_screen(
    args: argparse.Namespace,
    *,
    stdin=sys.stdin,
    stdout=sys.stdout,
) -> bool:
    return (
        not getattr(args, "status", False)
        and not getattr(args, "manual", False)
        and getattr(args, "provider", None) is None
        and not getattr(args, "no_clear_screen", False)
        and stdin.isatty()
        and stdout.isatty()
    )


def run_clear_screen_wizard(args: argparse.Namespace) -> int:
    try:
        provider = cleared_screen_onboarding()
    except (KeyboardInterrupt, EOFError, WizardCancelled):
        print("SubSurf setup cancelled.")
        return 130

    next_args = argparse.Namespace(**vars(args))
    next_args.provider = provider
    next_args.manual = False
    print(f"Selected provider: {provider}")
    return run_wizard(next_args)


def cleared_screen_onboarding() -> str:
    wait_for_intro()
    while True:
        selected = choose_provider()
        if confirm_provider_start(selected):
            return PROVIDER_CHOICES[selected].provider


def wait_for_intro() -> None:
    render_intro_screen()
    prompt_next("Press Enter for next, or Q to quit: ")


def choose_provider() -> int:
    while True:
        render_provider_screen()
        value = input("Choose 1 or 2, or Q to quit [1]: ").strip().lower()
        if value in {"", "1", "claude", "c"}:
            return 0
        if value in {"2", "codex", "o"}:
            return 1
        if value in {"q", "quit", "exit"}:
            raise WizardCancelled("setup cancelled")
        print("Please choose 1 for Claude Code or 2 for Codex.")


def confirm_provider_start(selected: int) -> bool:
    while True:
        render_plan_screen(PROVIDER_CHOICES[selected])
        value = input("Press Enter to start, B to go back, or Q to quit: ").strip().lower()
        if value == "":
            return True
        if value in {"b", "back"}:
            return False
        if value in {"q", "quit", "exit"}:
            raise WizardCancelled("setup cancelled")
        print("Press Enter to start, B to go back, or Q to quit.")


def prompt_next(message: str) -> None:
    value = input(message).strip().lower()
    if value in {"q", "quit", "exit"}:
        raise WizardCancelled("setup cancelled")


def render_intro_screen() -> None:
    lines = base_screen_lines("What This Is", step=1)
    width = screen_width()
    lines.extend(wrap_paragraph(
        "SubSurf is a local credential bridge. You sign into Claude Code or Codex "
        "inside an isolated profile, then SubSurf keeps that session fresh and "
        "writes attach files your own apps can use.",
        width,
    ))
    lines.append("")
    lines.extend(wrap_paragraph(
        "The important safety rule: the wizard does not use your normal ~/.claude "
        "or ~/.codex directories unless you explicitly override the guard.",
        width,
        color=ANSI_GREEN,
    ))
    lines.append("")
    lines.extend(wrap_paragraph(
        "Flow: choose provider, log in, discover account models, start keepalive "
        "where needed, then attach a sample app.",
        width,
    ))
    write_screen(lines)


def render_provider_screen() -> None:
    lines = base_screen_lines("Choose Provider", step=2)
    width = screen_width()
    lines.extend(wrap_paragraph(
        "Pick the subscription/login type SubSurf should isolate and attach.",
        width,
    ))
    lines.append("")
    for index, choice in enumerate(PROVIDER_CHOICES):
        lines.append(paint(ANSI_CYAN, f"[{index + 1}] {choice.title}"))
        lines.extend(wrap_paragraph(choice.detail, width - 6, prefix="      "))
        lines.append("")
    write_screen(lines)


def render_plan_screen(choice: ProviderChoice) -> None:
    lines = base_screen_lines("Ready To Start", step=3)
    width = screen_width()
    lines.append(paint(ANSI_GREEN, choice.title))
    lines.append("")
    if choice.provider == "claude":
        steps = [
            "Create or reuse a SubSurf install id.",
            "Open Claude Code with an isolated CLAUDE_CONFIG_DIR.",
            "You run /login, finish browser auth, then run /exit.",
            "SubSurf publishes the token, starts keepalive, and writes attach files.",
        ]
    else:
        steps = [
            "Prepare an isolated CODEX_HOME.",
            "Run Codex login inside that isolated home.",
            "Discover the models available on that account.",
            "Write attach files so another app can use the isolated login.",
        ]
    for index, step in enumerate(steps, start=1):
        lines.extend(wrap_paragraph(f"{index}. {step}", width, color=ANSI_WHITE))
    lines.append("")
    lines.extend(wrap_paragraph(
        "The cleared setup page ends before the external CLI launches so Claude Code "
        "or Codex gets a normal terminal.",
        width,
        color=ANSI_DIM,
    ))
    write_screen(lines)


def base_screen_lines(title: str, *, step: int) -> list[str]:
    width = screen_width()
    logo = SUBSURF_LOGO if width >= 58 else ("SUBSURF",)
    lines = [""]
    lines.extend(paint(ANSI_CYAN, line) for line in logo)
    lines.append("")
    lines.append(paint(ANSI_PURPLE, "Simple credential surfacing for local AI apps"))
    lines.append(paint(ANSI_DIM, "-" * min(width, 72)))
    lines.append("")
    lines.append(paint(ANSI_WHITE, f"Step {step}/3: {title}"))
    lines.append("")
    return lines


def screen_width() -> int:
    columns = shutil.get_terminal_size((88, 28)).columns
    return max(40, min(columns - 8, 92))


def wrap_paragraph(
    text: str,
    width: int,
    *,
    prefix: str = "",
    color: str | None = None,
) -> list[str]:
    wrapped = textwrap.wrap(text, width=max(24, width - len(prefix))) or [""]
    lines = [f"{prefix}{line}" for line in wrapped]
    if color:
        return [paint(color, line) for line in lines]
    return lines


def clear_terminal(stdout=sys.stdout) -> None:
    stdout.write("\033[2J\033[H")
    stdout.flush()


def write_screen(lines: list[str], stdout=sys.stdout) -> None:
    size = shutil.get_terminal_size((88, 28))
    clear_terminal(stdout)
    for line in lines[: max(1, size.lines - 2)]:
        stdout.write(f"{line}\n")
    stdout.flush()


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
    provider = getattr(args, "provider", None)
    if provider is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
        provider = prompt_provider() if getattr(args, "manual", False) or interactive else "claude"
    if provider == "codex":
        return run_codex_wizard(args)

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


def run_codex_wizard(args: argparse.Namespace) -> int:
    try:
        heading("SubSurf Codex Setup Wizard")
        print("This walks through isolated Codex login and app attachment.")

        account_id = codex_auth.resolve_account_id(
            getattr(args, "account_id", None),
            install_id_file=getattr(args, "install_id_file", DEFAULT_INSTALL_ID_FILE),
            create=True,
        )
        assert account_id is not None
        codex_home = getattr(args, "codex_home", None)
        paths = codex_auth.paths_for_account(account_id, codex_home=codex_home)
        allow_shared = getattr(args, "allow_shared_codex_home", False)
        codex_auth.validate_codex_home(paths, allow_shared=allow_shared)

        model_arg = getattr(args, "codex_model", None)
        model = (
            prompt(DEFAULT_CODEX_MODEL, "Codex model")
            if getattr(args, "manual", False) and model_arg is None
            else (model_arg or DEFAULT_CODEX_MODEL)
        )
        model = resolve_model_id(model)

        heading("Configuration")
        print(f"Account id:   {paths.account_id}")
        print(f"CODEX_HOME:   {paths.codex_home}")
        print(f"Auth file:    {paths.auth_file}")
        print(f"Codex model:  {model}")
        print(f"Codex CLI:    {shutil.which('codex') or 'not found'}")

        heading("Prepare Codex Home")
        codex_auth.ensure_codex_home(paths, allow_shared=allow_shared, model=model)
        print(f"wrote {paths.config_file}")

        heading("Codex Login")
        if getattr(args, "skip_login", False):
            print("Skipping launch because --skip-login was provided.")
        else:
            if not shutil.which("codex"):
                raise WizardError("Codex CLI was not found on PATH.")
            login_args = argparse.Namespace(
                device_auth=getattr(args, "codex_device_auth", False),
                with_api_key=getattr(args, "codex_with_api_key", False),
                with_access_token=getattr(args, "codex_with_access_token", False),
                model=model,
                print_command=False,
                allow_shared_codex_home=allow_shared,
            )
            rc = codex_auth.run_codex_login(paths, login_args)
            if rc != 0:
                raise WizardError(f"codex login exited with status {rc}")

        heading("Discover Available Codex Models")
        requested_model = (
            model if getattr(args, "manual", False) and model_arg is None else model_arg
        )
        model = refresh_codex_model_selection(
            paths,
            requested_model=requested_model,
            current_model=model,
            allow_shared=allow_shared,
        )

        heading("Attach")
        attach_dir = getattr(args, "attach_dir", None) or DEFAULT_ATTACH_DIR
        plan = codex_auth.build_attach_plan(
            attach_dir,
            paths,
            write_examples=True,
        )
        written = codex_auth.write_attach_files(
            plan,
            overwrite=(
                getattr(args, "overwrite_attach", None)
                if getattr(args, "overwrite_attach", None) is not None
                else True
            ),
        )
        for path in written:
            print(f"wrote {path}")
        codex_auth.print_attach_instructions(paths, app_dir=attach_dir)

        heading("Done")
        print("SubSurf Codex login is ready for apps that run with the isolated CODEX_HOME.")
        return 0
    except (WizardError, codex_auth.CodexAuthError, FileExistsError) as exc:
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
        codex_paths = codex_auth.paths_for_account(account_id)
        codex_status = codex_auth.summarize_auth(codex_auth.load_auth_json(codex_paths))
        print(f"Codex home:    {codex_paths.codex_home}")
        print(f"Codex auth:    {codex_paths.auth_file} {'exists' if codex_status.exists else 'missing'}")
        print(f"Codex mode:    {codex_status.mode or 'not logged in'}")
    print(f"Daemon pid:    {pid.read_text().strip() if pid.exists() else 'not recorded'}")
    return 0


def refresh_codex_model_selection(
    paths: codex_auth.CodexPaths,
    *,
    requested_model: str | None,
    current_model: str,
    allow_shared: bool,
) -> str:
    try:
        models = codex_auth.discover_models(paths)
    except (codex_auth.CodexAuthError, codex_auth.model_discovery.ModelDiscoveryError) as exc:
        print(f"Live model discovery unavailable: {exc}")
        print(f"Using configured Codex model: {current_model}")
        return current_model

    available_ids = [model.id for model in models]
    print(f"Discovered {len(available_ids)} account model(s).")
    if requested_model:
        selected = choose_available_model(available_ids, requested=requested_model)
        if selected not in set(available_ids):
            print(f"Warning: requested model {selected} was not in the discovered account list.")
        return selected

    selected = choose_available_model(available_ids)
    if selected != current_model:
        codex_auth.ensure_codex_home(paths, allow_shared=allow_shared, model=selected)
        print(f"Updated Codex model from {current_model} to account-available {selected}.")
    else:
        print(f"Using account-available Codex model: {selected}")
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SubSurf setup wizard")
    parser.add_argument("--provider", choices=("claude", "codex"))
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
    parser.add_argument("--codex-home")
    parser.add_argument("--codex-device-auth", action="store_true")
    parser.add_argument("--codex-with-api-key", action="store_true")
    parser.add_argument("--codex-with-access-token", action="store_true")
    parser.add_argument("--codex-model")
    parser.add_argument(
        "--allow-shared-codex-home",
        action="store_true",
        help="allow using ~/.codex instead of an isolated SubSurf CODEX_HOME",
    )
    parser.add_argument("--start-daemon", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--attach-dir")
    parser.add_argument("--overwrite-attach", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--status", action="store_true", help="show token/daemon status and exit")
    parser.add_argument(
        "--no-clear-screen",
        dest="no_clear_screen",
        action="store_true",
        help="use the classic line-oriented wizard instead of cleared-screen onboarding",
    )
    parser.add_argument(
        "--no-fullscreen",
        dest="no_clear_screen",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.status:
        return status(args)
    if should_launch_clear_screen(args):
        return run_clear_screen_wizard(args)
    return run_wizard(args)


if __name__ == "__main__":
    raise SystemExit(main())
