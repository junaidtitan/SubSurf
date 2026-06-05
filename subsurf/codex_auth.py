"""Isolated Codex login helpers for SubSurf.

This module treats Codex as a separate auth provider from Claude Code. It never
uses the user's default ``~/.codex`` home unless explicitly allowed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from subsurf import model_discovery
from subsurf.openai_models import DEFAULT_CODEX_MODEL, model_ids, resolve_model_id
from subsurf.openai_models import rows as openai_model_rows


DEFAULT_STATE_ROOT = "~/.config/subsurf"
DEFAULT_INSTALLS_DIR = f"{DEFAULT_STATE_ROOT}/installs"
DEFAULT_INSTALL_ID_FILE = f"{DEFAULT_STATE_ROOT}/install_id"
DEFAULT_ATTACH_DIR = "sample-app"


class CodexAuthError(RuntimeError):
    """Recoverable Codex auth setup/read error."""


@dataclass(frozen=True)
class CodexPaths:
    """Filesystem locations used for one isolated Codex login."""

    account_id: str
    state_dir: Path
    codex_home: Path
    config_file: Path
    auth_file: Path


@dataclass(frozen=True)
class CodexAuthStatus:
    """Summarized auth state from ``CODEX_HOME/auth.json``."""

    exists: bool
    mode: str | None
    has_api_key: bool
    has_access_token: bool
    has_refresh_token: bool
    has_agent_identity: bool
    account_id: str | None = None
    email: str | None = None
    plan_type: str | None = None


@dataclass(frozen=True)
class CodexAttachPlan:
    """Files and environment used to attach an app to isolated Codex auth."""

    app_dir: Path
    env_file: Path
    paths: CodexPaths
    write_examples: bool


CODEX_CLI_EXAMPLE = '''"""Run Codex through SubSurf's isolated Codex login.

Load `.env.subsurf.codex` however your app normally loads env files. The key is
that CODEX_HOME points at SubSurf's isolated Codex home, not your normal
~/.codex.
"""

import os
import subprocess


def main() -> None:
    env = os.environ.copy()
    env["CODEX_HOME"] = os.environ["SUBSURF_CODEX_HOME"]
    subprocess.run(["codex", "login", "status"], env=env, check=True)


if __name__ == "__main__":
    main()
'''


CODEX_TOKEN_EXAMPLE = '''"""Read a bearer value from SubSurf's isolated Codex login.

This prints only metadata so you do not accidentally leak the token while
testing. Use the token only with Codex/OpenAI-compatible surfaces that accept
that exact credential type.
"""

import os
import shlex
import subprocess


def main() -> None:
    command = shlex.split(os.environ["SUBSURF_CODEX_TOKEN_COMMAND"])
    token = subprocess.check_output(command, text=True).strip()
    print(f"token_length={len(token)}")


if __name__ == "__main__":
    main()
'''


def load_existing_install_id(path: str | Path = DEFAULT_INSTALL_ID_FILE) -> str | None:
    install_id_path = Path(path).expanduser()
    if not install_id_path.exists():
        return None
    value = install_id_path.read_text().strip()
    return value or None


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


def resolve_account_id(
    account_id: str | None,
    *,
    install_id_file: str | Path = DEFAULT_INSTALL_ID_FILE,
    create: bool,
) -> str | None:
    if account_id:
        return account_id
    if create:
        return load_or_create_install_id(install_id_file)
    return load_existing_install_id(install_id_file)


def paths_for_account(
    account_id: str,
    *,
    codex_home: str | Path | None = None,
) -> CodexPaths:
    state_dir = Path(DEFAULT_INSTALLS_DIR).expanduser() / account_id
    home = Path(codex_home).expanduser() if codex_home else state_dir / "codex_home"
    return CodexPaths(
        account_id=account_id,
        state_dir=state_dir,
        codex_home=home,
        config_file=home / "config.toml",
        auth_file=home / "auth.json",
    )


def is_shared_codex_home(codex_home: str | Path) -> bool:
    return Path(codex_home).expanduser() == Path("~/.codex").expanduser()


def validate_codex_home(paths: CodexPaths, *, allow_shared: bool = False) -> None:
    if not is_shared_codex_home(paths.codex_home) or allow_shared:
        return
    isolated = paths_for_account(paths.account_id).codex_home
    raise CodexAuthError(
        "Refusing to use the shared Codex home `~/.codex`.\n\n"
        "SubSurf should use an isolated CODEX_HOME so Codex credentials do not "
        "collide with your normal Codex CLI/app session.\n\n"
        "Use this instead:\n"
        f"  --codex-home {isolated}\n\n"
        "Only override this guard if you intentionally want to share normal "
        "Codex credentials:\n"
        "  --allow-shared-codex-home",
    )


def ensure_codex_home(
    paths: CodexPaths,
    *,
    allow_shared: bool = False,
    model: str | None = None,
) -> None:
    validate_codex_home(paths, allow_shared=allow_shared)
    paths.codex_home.mkdir(parents=True, exist_ok=True)
    os.chmod(paths.codex_home, 0o700)
    write_codex_config(paths.config_file, model=model)


def write_codex_config(config_file: Path, *, model: str | None = None) -> None:
    """Force isolated credential storage and optionally set the Codex model."""
    if config_file.exists():
        lines = config_file.read_text().splitlines()
    else:
        lines = []

    found_storage = False
    found_model = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if _is_toml_assignment(stripped, "cli_auth_credentials_store"):
            out.append('cli_auth_credentials_store = "file"')
            found_storage = True
        elif model is not None and _is_toml_assignment(stripped, "model"):
            out.append(_toml_string_assignment("model", resolve_model_id(model)))
            found_model = True
        else:
            out.append(line)

    if model is not None and not found_model:
        if out and out[-1].strip():
            out.append("")
        out.append(_toml_string_assignment("model", resolve_model_id(model)))

    if not found_storage:
        if out and out[-1].strip():
            out.append("")
        out.append('cli_auth_credentials_store = "file"')

    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("\n".join(out).rstrip() + "\n")
    os.chmod(config_file, 0o600)


def _toml_string_assignment(key: str, value: str) -> str:
    return f"{key} = {json.dumps(value)}"


def _is_toml_assignment(stripped_line: str, key: str) -> bool:
    return stripped_line.startswith(f"{key} ") or stripped_line.startswith(f"{key}=")


def isolated_env(paths: CodexPaths) -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(paths.codex_home)
    return env


def codex_login_command(args: argparse.Namespace) -> list[str]:
    command = ["codex", "login"]
    if getattr(args, "device_auth", False):
        command.append("--device-auth")
    if getattr(args, "with_api_key", False):
        command.append("--with-api-key")
    if getattr(args, "with_access_token", False):
        command.append("--with-access-token")
    return command


def run_codex_login(paths: CodexPaths, args: argparse.Namespace) -> int:
    ensure_codex_home(
        paths,
        allow_shared=args.allow_shared_codex_home,
        model=getattr(args, "model", None),
    )
    if not shutil.which("codex"):
        raise CodexAuthError("Codex CLI was not found on PATH.")
    command = codex_login_command(args)
    if args.print_command:
        print(f"CODEX_HOME={paths.codex_home} " + " ".join(command))
        return 0
    return subprocess.run(command, env=isolated_env(paths)).returncode


def load_auth_json(paths: CodexPaths) -> dict[str, Any] | None:
    if not paths.auth_file.exists():
        return None
    try:
        data = json.loads(paths.auth_file.read_text())
    except json.JSONDecodeError as exc:
        raise CodexAuthError(f"Codex auth file is not valid JSON: {paths.auth_file}") from exc
    if not isinstance(data, dict):
        raise CodexAuthError(f"Codex auth file must contain a JSON object: {paths.auth_file}")
    return data


def summarize_auth(data: dict[str, Any] | None) -> CodexAuthStatus:
    if not data:
        return CodexAuthStatus(
            exists=False,
            mode=None,
            has_api_key=False,
            has_access_token=False,
            has_refresh_token=False,
            has_agent_identity=False,
        )

    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    id_claims = parse_jwt_payload(str(tokens.get("id_token") or ""))
    mode = data.get("auth_mode")
    if mode is None:
        mode = infer_auth_mode(data)
    return CodexAuthStatus(
        exists=True,
        mode=str(mode) if mode else None,
        has_api_key=bool(data.get("OPENAI_API_KEY")),
        has_access_token=bool(tokens.get("access_token")),
        has_refresh_token=bool(tokens.get("refresh_token")),
        has_agent_identity=bool(data.get("agent_identity")),
        account_id=(
            str(tokens.get("account_id"))
            if tokens.get("account_id")
            else _optional_str(id_claims.get("https://api.openai.com/auth", {}).get("chatgpt_account_id"))
        ),
        email=_optional_str(id_claims.get("email")),
        plan_type=_optional_str(
            id_claims.get("https://api.openai.com/auth", {}).get("chatgpt_plan_type"),
        ),
    )


def infer_auth_mode(data: dict[str, Any]) -> str | None:
    if data.get("agent_identity"):
        return "agentIdentity"
    if data.get("tokens"):
        return "chatgpt"
    if data.get("OPENAI_API_KEY"):
        return "apikey"
    return None


def parse_jwt_payload(jwt: str) -> dict[str, Any]:
    parts = jwt.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode((payload + padding).encode())
        data = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def extract_token(data: dict[str, Any] | None, *, kind: str = "any") -> str:
    if not data:
        raise CodexAuthError("Codex auth is missing. Run `subsurf-codex login` first.")
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    candidates = {
        "access-token": tokens.get("access_token"),
        "api-key": data.get("OPENAI_API_KEY"),
        "agent-identity": data.get("agent_identity"),
    }
    if kind == "any":
        for key in ("access-token", "agent-identity", "api-key"):
            value = candidates.get(key)
            if value:
                return str(value)
    else:
        value = candidates.get(kind)
        if value:
            return str(value)
    raise CodexAuthError(f"Codex auth does not contain a {kind} credential.")


def build_env(paths: CodexPaths) -> dict[str, str]:
    token_command = " ".join((
        "subsurf-codex",
        "token",
        "--account-id",
        shlex.quote(paths.account_id),
        "--codex-home",
        shlex.quote(str(paths.codex_home)),
    ))
    return {
        "SUBSURF_CODEX_HOME": str(paths.codex_home),
        "SUBSURF_CODEX_AUTH_FILE": str(paths.auth_file),
        "SUBSURF_CODEX_TOKEN_COMMAND": token_command,
        "CODEX_HOME": str(paths.codex_home),
    }


def env_text(env: dict[str, str]) -> str:
    return "".join(f"{key}={value}\n" for key, value in env.items())


def build_attach_plan(
    app_dir: str | Path,
    paths: CodexPaths,
    *,
    env_name: str = ".env.subsurf.codex",
    write_examples: bool = True,
) -> CodexAttachPlan:
    return CodexAttachPlan(
        app_dir=Path(app_dir).expanduser().resolve(),
        env_file=Path(app_dir).expanduser().resolve() / env_name,
        paths=paths,
        write_examples=write_examples,
    )


def model_cache_file(paths: CodexPaths) -> Path:
    return paths.state_dir / "codex_models.json"


def discover_models(
    paths: CodexPaths,
    *,
    http_get: model_discovery.HttpGet = model_discovery.default_http_get,
    use_cache: bool = True,
) -> list[model_discovery.DiscoveredModel]:
    """Discover models available to this isolated Codex account."""
    cache_file = model_cache_file(paths)
    auth = load_auth_json(paths)
    if not auth:
        if use_cache:
            cached = model_discovery.read_model_cache(cache_file)
            if cached:
                return cached
        raise CodexAuthError("Codex auth is missing. Run `subsurf-codex login` first.")

    try:
        if auth.get("OPENAI_API_KEY"):
            return model_discovery.discover_openai_models(
                str(auth["OPENAI_API_KEY"]),
                cache_file=cache_file,
                http_get=http_get,
            )

        tokens = auth.get("tokens") if isinstance(auth.get("tokens"), dict) else {}
        access_token = tokens.get("access_token")
        if access_token:
            status = summarize_auth(auth)
            return model_discovery.discover_chatgpt_codex_models(
                str(access_token),
                account_id=status.account_id,
                cache_file=cache_file,
                http_get=http_get,
            )
    except model_discovery.ModelDiscoveryError:
        if use_cache:
            cached = model_discovery.read_model_cache(cache_file)
            if cached:
                return cached
        raise

    if use_cache:
        cached = model_discovery.read_model_cache(cache_file)
        if cached:
            return cached
    raise CodexAuthError("Codex auth does not contain a discoverable model-list credential.")


def write_attach_files(plan: CodexAttachPlan, *, overwrite: bool = False) -> list[Path]:
    plan.app_dir.mkdir(parents=True, exist_ok=True)
    files: dict[Path, str] = {
        plan.env_file: env_text(build_env(plan.paths)),
    }
    if plan.write_examples:
        files[plan.app_dir / "subsurf_codex_cli_example.py"] = CODEX_CLI_EXAMPLE
        files[plan.app_dir / "subsurf_codex_token_example.py"] = CODEX_TOKEN_EXAMPLE

    written: list[Path] = []
    for path, text in files.items():
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path} already exists; use --overwrite to replace it")
        path.write_text(text)
        written.append(path)
    return written


def print_attach_instructions(paths: CodexPaths, *, app_dir: str | Path | None = None) -> None:
    env = build_env(paths)
    print()
    print("Attach isolated Codex login to another app")
    print("------------------------------------------")
    if app_dir:
        print(f"App dir:    {Path(app_dir).expanduser().resolve()}")
    print(f"CODEX_HOME: {paths.codex_home}")
    print(f"Auth file:  {paths.auth_file}")
    print()
    print("Set these in your app process:")
    for key, value in env.items():
        print(f"  export {key}={value}")
    print()
    print("Use cases:")
    print("  - Run Codex CLI/subprocesses with CODEX_HOME set to this isolated home.")
    print("  - Use `subsurf-codex token` only for trusted code that accepts this credential type.")
    print()
    print("Safety:")
    print("  Do not point SubSurf at ~/.codex unless you intentionally pass --allow-shared-codex-home.")


def print_status(paths: CodexPaths, status: CodexAuthStatus) -> None:
    print(f"Account id:       {paths.account_id}")
    print(f"CODEX_HOME:       {paths.codex_home}")
    print(f"Config file:      {paths.config_file} {'exists' if paths.config_file.exists() else 'missing'}")
    print(f"Auth file:        {paths.auth_file} {'exists' if paths.auth_file.exists() else 'missing'}")
    print(f"Auth mode:        {status.mode or 'not logged in'}")
    print(f"API key:          {'present' if status.has_api_key else 'missing'}")
    print(f"Access token:     {'present' if status.has_access_token else 'missing'}")
    print(f"Refresh token:    {'present' if status.has_refresh_token else 'missing'}")
    print(f"Agent identity:   {'present' if status.has_agent_identity else 'missing'}")
    if status.account_id:
        print(f"Workspace/account:{status.account_id}")
    if status.email:
        print(f"Email:            {status.email}")
    if status.plan_type:
        print(f"Plan type:        {status.plan_type}")


def resolve_paths_from_args(args: argparse.Namespace, *, create_account: bool) -> CodexPaths:
    account_id = resolve_account_id(
        getattr(args, "account_id", None),
        install_id_file=getattr(args, "install_id_file", DEFAULT_INSTALL_ID_FILE),
        create=create_account,
    )
    if not account_id:
        raise CodexAuthError("No SubSurf install id is recorded. Run setup or pass --account-id.")
    return paths_for_account(account_id, codex_home=getattr(args, "codex_home", None))


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account-id")
    parser.add_argument("--codex-home")
    parser.add_argument("--install-id-file", default=DEFAULT_INSTALL_ID_FILE, help=argparse.SUPPRESS)
    parser.add_argument(
        "--allow-shared-codex-home",
        action="store_true",
        help="allow using ~/.codex instead of an isolated SubSurf CODEX_HOME",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage isolated Codex login for SubSurf")
    sub = parser.add_subparsers(dest="command")

    prepare = sub.add_parser("prepare", help="create isolated CODEX_HOME and config")
    add_common_args(prepare)
    prepare.add_argument("--model", default=DEFAULT_CODEX_MODEL)

    login = sub.add_parser("login", help="run `codex login` inside isolated CODEX_HOME")
    add_common_args(login)
    login.add_argument("--model", default=DEFAULT_CODEX_MODEL)
    login.add_argument("--device-auth", action="store_true", help="pass --device-auth to codex login")
    login.add_argument("--with-api-key", action="store_true", help="read API key from stdin")
    login.add_argument("--with-access-token", action="store_true", help="read Codex access token from stdin")
    login.add_argument("--print-command", action="store_true", help="print the command instead of running it")

    status = sub.add_parser("status", help="show isolated Codex login status")
    add_common_args(status)

    token = sub.add_parser("token", help="print the stored Codex credential to stdout")
    add_common_args(token)
    token.add_argument(
        "--kind",
        choices=("any", "access-token", "api-key", "agent-identity"),
        default="any",
    )

    models = sub.add_parser("models", help="list Codex/OpenAI model aliases")
    add_common_args(models)
    models.add_argument("--aliases", action="store_true", help="include aliases")
    models.add_argument("--live", action="store_true", help="query the isolated account")
    models.add_argument("--json", action="store_true", help="print machine-readable JSON")

    env = sub.add_parser("env", help="print app environment exports")
    add_common_args(env)

    attach = sub.add_parser("attach", help="write .env and examples for another app")
    add_common_args(attach)
    attach.add_argument("--app-dir", default=DEFAULT_ATTACH_DIR)
    attach.add_argument("--env-name", default=".env.subsurf.codex")
    attach.add_argument("--no-examples", action="store_true")
    attach.add_argument("--overwrite", action="store_true")
    attach.add_argument("--print-only", action="store_true")

    logout = sub.add_parser("logout", help="remove isolated auth.json")
    add_common_args(logout)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        args.command = "status"
    try:
        if args.command == "models":
            if args.live:
                paths = resolve_paths_from_args(args, create_account=False)
                models = discover_models(paths)
                entries = model_discovery.openai_entries(models)
                if args.json:
                    print(json.dumps({"object": "list", "data": entries}, indent=2))
                else:
                    for entry in entries:
                        print(entry["id"])
                return 0

            if args.json:
                print(json.dumps(openai_model_rows(), indent=2))
            else:
                for model_id in model_ids(include_aliases=args.aliases):
                    print(model_id)
            return 0

        create_account = args.command in {"prepare", "login", "attach"}
        paths = resolve_paths_from_args(args, create_account=create_account)

        if args.command == "prepare":
            ensure_codex_home(
                paths,
                allow_shared=args.allow_shared_codex_home,
                model=args.model,
            )
            print(f"Prepared isolated CODEX_HOME: {paths.codex_home}")
            print(f"Codex model: {resolve_model_id(args.model)}")
            return 0

        if args.command == "login":
            return run_codex_login(paths, args)

        if args.command == "status":
            print_status(paths, summarize_auth(load_auth_json(paths)))
            return 0

        if args.command == "token":
            token = extract_token(load_auth_json(paths), kind=args.kind)
            print(token)
            return 0

        if args.command == "env":
            for key, value in build_env(paths).items():
                print(f"export {key}={value}")
            return 0

        if args.command == "attach":
            ensure_codex_home(paths, allow_shared=args.allow_shared_codex_home)
            if args.print_only:
                print_attach_instructions(paths, app_dir=args.app_dir)
                return 0
            plan = build_attach_plan(
                args.app_dir,
                paths,
                env_name=args.env_name,
                write_examples=not args.no_examples,
            )
            written = write_attach_files(plan, overwrite=args.overwrite)
            for path in written:
                print(f"wrote {path}")
            print_attach_instructions(paths, app_dir=args.app_dir)
            return 0

        if args.command == "logout":
            validate_codex_home(paths, allow_shared=args.allow_shared_codex_home)
            if paths.auth_file.exists():
                paths.auth_file.unlink()
                print(f"Removed {paths.auth_file}")
            else:
                print(f"No auth file at {paths.auth_file}")
            return 0

    except (CodexAuthError, FileExistsError, model_discovery.ModelDiscoveryError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
