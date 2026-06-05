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
from subsurf import codex_auth
from subsurf.openai_models import DEFAULT_CODEX_MODEL, choose_available_model, resolve_model_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SubSurf setup flow")
    parser.add_argument("--provider", choices=("claude", "codex"), default="claude")
    parser.add_argument("--account-id")
    parser.add_argument("--app-dir", default=wizard.DEFAULT_ATTACH_DIR)
    parser.add_argument("--no-start-daemon", action="store_true")
    parser.add_argument("--skip-login", action="store_true")
    parser.add_argument("--no-live-checks", action="store_true")
    parser.add_argument("--no-overwrite-attach", action="store_true")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--codex-home")
    parser.add_argument("--codex-device-auth", action="store_true")
    parser.add_argument("--codex-with-api-key", action="store_true")
    parser.add_argument("--codex-with-access-token", action="store_true")
    parser.add_argument("--codex-model")
    parser.add_argument(
        "--allow-shared-codex-home",
        action="store_true",
        help="allow using ~/.codex for Codex-provider setup",
    )
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
    except (wizard.WizardError, codex_auth.CodexAuthError) as exc:
        print()
        print("Setup stopped")
        print("-------------")
        print(str(exc))
        return 2


def run_setup(args: argparse.Namespace) -> int:
    if args.provider == "codex":
        return run_codex_setup(args)

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


def run_codex_setup(args: argparse.Namespace) -> int:
    print("SubSurf Codex setup")
    print("===================")
    print("This uses an isolated CODEX_HOME and file-based Codex credential storage.")
    print("It does not touch your normal ~/.codex unless explicitly allowed.")

    step(1, "Preflight")
    account_id = codex_auth.resolve_account_id(
        args.account_id,
        install_id_file=args.install_id_file,
        create=True,
    )
    assert account_id is not None
    paths = codex_auth.paths_for_account(account_id, codex_home=args.codex_home)
    codex_auth.validate_codex_home(paths, allow_shared=args.allow_shared_codex_home)
    print(f"Codex CLI:  {shutil.which('codex') or 'not found'}")
    print(f"Account id: {paths.account_id}")
    print(f"CODEX_HOME: {paths.codex_home}")
    print(f"Auth file:  {paths.auth_file}")
    if not args.skip_login and not shutil.which("codex"):
        raise wizard.WizardError("Codex CLI was not found on PATH.")

    step(2, "Prepare isolated Codex home")
    requested_codex_model = args.codex_model or DEFAULT_CODEX_MODEL
    codex_model = resolve_model_id(requested_codex_model)
    codex_auth.ensure_codex_home(
        paths,
        allow_shared=args.allow_shared_codex_home,
        model=codex_model,
    )
    print(f"wrote {paths.config_file}")
    print(f"Codex model: {codex_model}")

    step(3, "Codex login")
    if args.skip_login:
        print("Skipped because --skip-login was set.")
    else:
        login_args = argparse.Namespace(
            device_auth=args.codex_device_auth,
            with_api_key=args.codex_with_api_key,
            with_access_token=args.codex_with_access_token,
            model=codex_model,
            print_command=False,
            allow_shared_codex_home=args.allow_shared_codex_home,
        )
        rc = codex_auth.run_codex_login(paths, login_args)
        if rc != 0:
            raise wizard.WizardError(f"codex login exited with status {rc}")

    step(4, "Discover available Codex models")
    codex_model = refresh_codex_model_selection(
        paths,
        requested_model=args.codex_model,
        current_model=codex_model,
        allow_shared=args.allow_shared_codex_home,
    )

    step(5, "Write app attachment")
    plan = codex_auth.build_attach_plan(
        args.app_dir,
        paths,
        write_examples=True,
    )
    written = codex_auth.write_attach_files(plan, overwrite=not args.no_overwrite_attach)
    for path in written:
        print(f"wrote {path}")
    codex_auth.print_attach_instructions(paths, app_dir=args.app_dir)

    step(6, "Status")
    codex_auth.print_status(paths, codex_auth.summarize_auth(codex_auth.load_auth_json(paths)))

    if not args.no_live_checks:
        print()
        print("Live checks")
        print("-----------")
        print("Run a Codex command through the isolated home when you are ready:")
        print(f"  CODEX_HOME={paths.codex_home} codex login status")

    print()
    print("Done")
    print("====")
    print("SubSurf Codex login is ready for apps that run with the isolated CODEX_HOME.")
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


if __name__ == "__main__":
    raise SystemExit(main())
