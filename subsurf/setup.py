"""Plain terminal setup flow for SubSurf."""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import shutil
import subprocess
from pathlib import Path

from subsurf import demo, wizard
from subsurf.attach import build_attach_plan, write_attach_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SubSurf setup flow")
    parser.add_argument("--account-id")
    parser.add_argument("--app-dir", default=wizard.DEFAULT_ATTACH_DIR)
    parser.add_argument("--no-start-daemon", action="store_true")
    parser.add_argument("--skip-login", action="store_true")
    parser.add_argument("--no-live-checks", action="store_true")
    parser.add_argument("--no-overwrite-attach", action="store_true")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--install-id-file", default=wizard.DEFAULT_INSTALL_ID_FILE, help=argparse.SUPPRESS)
    return parser


def wizard_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        account_id=args.account_id,
        label=args.account_id,
        config_dir=None,
        install_id_file=args.install_id_file,
        token_file=None,
        accounts_file=None,
        pool_file=None,
        interval=60,
        manual=False,
        skip_login=args.skip_login,
        allow_shared_claude_config=False,
        launch_claude=None,
        start_daemon=not args.no_start_daemon,
        attach_dir=args.app_dir,
        overwrite_attach=not args.no_overwrite_attach,
        status=False,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_setup(args)
    except wizard.WizardError as exc:
        print()
        print("Setup stopped")
        print("-------------")
        print(str(exc))
        return 2


def run_setup(args: argparse.Namespace) -> int:
    print("SubSurf setup")
    print("=============")
    print("This uses an isolated Claude Code config and per-install token files.")
    print("Do not run /login in your normal Claude Code terminal for this setup.")

    step(1, "Preflight")
    options = wizard.resolve_options(wizard_args(args))
    wizard.validate_options(options)
    print_preflight(options)
    require_tools(options)

    step(2, "Claude login")
    run_claude_login(options)

    step(3, "Publish OAuth token")
    wizard.enroll_and_publish(options)

    step(4, "Keep token alive")
    wizard.start_daemon(options)

    step(5, "Write sample app")
    write_sample_app(options)

    if args.no_live_checks:
        step(6, "Live checks")
        print("Skipped because --no-live-checks was set.")
    else:
        step(6, "Live checks")
        run_live_checks(options, model=args.model)

    print()
    print("Done")
    print("====")
    print("SubSurf is ready.")
    print(f"Token:      {Path(f'{options.token_file}_{options.account_id}').expanduser()}")
    print(f"Sample app: {Path(options.attach_dir or wizard.DEFAULT_ATTACH_DIR).resolve()}")
    print()
    print("Repeatable test:")
    print("  python -m subsurf.demo")
    print()
    print("Status:")
    print("  python -m subsurf.wizard --status")
    return 0


def step(index: int, title: str) -> None:
    print()
    print(f"{index}. {title}")
    print("-" * (len(title) + 3))


def print_preflight(options: wizard.WizardOptions) -> None:
    token_path = Path(f"{options.token_file}_{options.account_id}").expanduser()
    print(f"Platform:      {platform.system()}")
    print(f"Claude CLI:    {shutil.which('claude') or 'not found'}")
    print(f"security:      {shutil.which('security') or 'not found'}")
    print(f"Account id:    {options.account_id}")
    print(f"Claude config: {Path(options.config_dir).expanduser()}")
    print(f"Token file:    {token_path}")
    print(f"Sample app:    {Path(options.attach_dir or wizard.DEFAULT_ATTACH_DIR).resolve()}")


def require_tools(options: wizard.WizardOptions) -> None:
    if platform.system() != "Darwin":
        raise wizard.WizardError("SubSurf's Claude Code Keychain bridge must run on macOS.")
    if not shutil.which("security"):
        raise wizard.WizardError("macOS `security` CLI was not found on PATH.")
    if not options.skip_login and not shutil.which("claude"):
        raise wizard.WizardError("Claude CLI was not found on PATH.")


def run_claude_login(options: wizard.WizardOptions) -> None:
    print("SubSurf will open Claude with this isolated config:")
    print(f"  CLAUDE_CONFIG_DIR={Path(options.config_dir).expanduser()}")
    print()
    print("When Claude opens:")
    print("  1. Run /login")
    print("  2. Finish browser auth")
    print("  3. Run /exit")
    print()

    if options.skip_login:
        print("Skipped because --skip-login was set.")
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


def write_sample_app(options: wizard.WizardOptions) -> None:
    app_dir = options.attach_dir or wizard.DEFAULT_ATTACH_DIR
    plan = build_attach_plan(
        app_dir,
        account_id=options.account_id,
        token_file=options.token_file,
        write_examples=True,
    )
    written = write_attach_files(plan, overwrite=options.overwrite_attach)
    for path in written:
        print(f"wrote {path}")


def run_live_checks(options: wizard.WizardOptions, *, model: str) -> None:
    paths = demo.resolve_demo_paths(
        argparse.Namespace(
            account_id=options.account_id,
            app_dir=options.attach_dir or wizard.DEFAULT_ATTACH_DIR,
            token_file=options.token_file,
            accounts_file=options.accounts_file,
            pool_file=options.pool_file,
        ),
    )

    text = asyncio.run(
        demo._complete_with_engine(
            paths,
            model=model,
            prompt=demo.DEFAULT_PROMPT,
        ),
    )
    print(f"Python piggyback: OK ({text.strip()})")

    payload = demo._gateway_completion(
        paths,
        model=model,
        prompt=demo.DEFAULT_PROMPT,
    )
    reply = payload["choices"][0]["message"]["content"].strip()
    print(f"Gateway piggyback: OK ({reply})")


if __name__ == "__main__":
    raise SystemExit(main())
