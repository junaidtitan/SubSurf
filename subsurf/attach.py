"""Helpers for attaching SubSurf OAuth tokens to another application."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from subsurf.config import SubSurfSettings, get_settings


DEFAULT_INSTALL_ID_FILE = "~/.config/subsurf/install_id"
DEFAULT_INSTALLS_DIR = "~/.config/subsurf/installs"
DEFAULT_TOKEN_FILE = "~/.config/subsurf/oauth_token"


PYTHON_EXAMPLE = '''"""Minimal SubSurf attachment example.

Install SubSurf in the app environment, load `.env.subsurf` however your app
normally loads env files, and keep `subsurf-wizard`/`subsurf-bridge` running so
the token file stays fresh.
"""

import asyncio

from subsurf import SubSurfEngine


async def main() -> None:
    engine = SubSurfEngine()
    text = await engine.complete([
        {"role": "user", "content": "Reply with a short hello from SubSurf."},
    ])
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
'''


DIRECT_SDK_EXAMPLE = '''"""Direct Anthropic SDK attachment example.

Use this when your app already has its own LLM wrapper and only needs the
OAuth token file. The important bit is `auth_token=token`, not `api_key=...`.
"""

from pathlib import Path
import os

import anthropic


TOKEN_PATH = Path(os.environ["SUBSURF_OAUTH_TOKEN_PATH"]).expanduser()
CC_HEADERS = {
    "anthropic-beta": "oauth-2025-04-20,claude-code-20250219",
    "User-Agent": "claude-cli/2.1.81 (external, cli)",
}
CC_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."


def build_client() -> anthropic.AsyncAnthropic:
    token = TOKEN_PATH.read_text().strip()
    return anthropic.AsyncAnthropic(auth_token=token, default_headers=CC_HEADERS)
'''


LITELLM_EXAMPLE = '''"""LiteLLM attachment example.

Install SubSurf in the app environment, load `.env.subsurf`, register the
provider once at process startup, then call models as `subsurf/<model>`.
"""

import litellm

from subsurf.litellm_provider import register_subsurf_provider


register_subsurf_provider()

response = litellm.completion(
    model="subsurf/claude-sonnet-4-6",
    messages=[
        {"role": "user", "content": "Reply with a short hello from SubSurf."},
    ],
    max_tokens=128,
)
print(response.choices[0].message.content)
'''


@dataclass(frozen=True)
class AttachPlan:
    """Files and environment used to connect another app to SubSurf."""

    app_dir: Path
    env_file: Path
    token_path: Path
    model: str
    write_examples: bool


def token_path_for_account(account_id: str | None, base_token_file: str) -> Path:
    base = Path(base_token_file).expanduser()
    if account_id:
        return Path(f"{base}_{account_id}").expanduser()
    return base


def load_existing_install_id(path: str | Path | None = None) -> str | None:
    install_id_path = Path(path or DEFAULT_INSTALL_ID_FILE).expanduser()
    if not install_id_path.exists():
        return None
    value = install_id_path.read_text().strip()
    return value or None


def default_token_file_for_account(account_id: str) -> str:
    return str(Path(DEFAULT_INSTALLS_DIR).expanduser() / account_id / "oauth_token")


def build_env(settings: SubSurfSettings, token_path: Path) -> dict[str, str]:
    return {
        "SUBSURF_OAUTH_TOKEN_PATH": str(token_path),
        "SUBSURF_REASONING_MODEL": settings.reasoning_model,
        "SUBSURF_OAUTH_SPOOF": "1",
    }


def env_text(env: dict[str, str]) -> str:
    return "".join(f"{key}={value}\n" for key, value in env.items())


def build_attach_plan(
    app_dir: str | Path,
    *,
    account_id: str | None = None,
    token_file: str | None = None,
    env_name: str = ".env.subsurf",
    write_examples: bool = True,
    settings: SubSurfSettings | None = None,
) -> AttachPlan:
    cfg = settings or get_settings()
    root = Path(app_dir).expanduser().resolve()
    resolved_account_id = account_id or load_existing_install_id()
    resolved_token_file = token_file or (
        default_token_file_for_account(resolved_account_id)
        if resolved_account_id
        else DEFAULT_TOKEN_FILE
    )
    return AttachPlan(
        app_dir=root,
        env_file=root / env_name,
        token_path=token_path_for_account(resolved_account_id, resolved_token_file),
        model=cfg.reasoning_model,
        write_examples=write_examples,
    )


def write_attach_files(plan: AttachPlan, *, overwrite: bool = False) -> list[Path]:
    """Write `.env.subsurf` and optional examples into an app directory."""
    plan.app_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    written: list[Path] = []

    files: dict[Path, str] = {
        plan.env_file: env_text(build_env(settings, plan.token_path)),
    }
    if plan.write_examples:
        files[plan.app_dir / "subsurf_client_example.py"] = PYTHON_EXAMPLE
        files[plan.app_dir / "subsurf_direct_anthropic_example.py"] = DIRECT_SDK_EXAMPLE
        files[plan.app_dir / "subsurf_litellm_example.py"] = LITELLM_EXAMPLE

    for path, text in files.items():
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path} already exists; use --overwrite to replace it")
        path.write_text(text)
        written.append(path)
    return written


def print_attach_instructions(plan: AttachPlan) -> None:
    env = build_env(get_settings(), plan.token_path)
    print("\nAttach SubSurf to another app")
    print("--------------------------")
    print(f"Token file: {plan.token_path}")
    print(f"Env file:   {plan.env_file}")
    print()
    print("Set these in your app process:")
    for key, value in env.items():
        print(f"  export {key}={value}")
    print()
    print("Python app, easiest path:")
    print("  from subsurf import SubSurfEngine")
    print("  text = await SubSurfEngine().complete([{'role': 'user', 'content': 'hi'}])")
    print()
    print("LiteLLM app:")
    print("  from subsurf.litellm_provider import register_subsurf_provider")
    print("  register_subsurf_provider()")
    print("  litellm.completion(model='subsurf/claude-sonnet-4-6', messages=[...])")
    print()
    print("Existing Anthropic wrapper:")
    print("  token = Path(os.environ['SUBSURF_OAUTH_TOKEN_PATH']).read_text().strip()")
    print("  client = anthropic.AsyncAnthropic(auth_token=token, default_headers=CC_HEADERS)")
    print()
    print("Keepalive requirement:")
    print("  Keep the wizard-started daemon running; check with `subsurf-wizard --status`.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attach SubSurf OAuth to another app")
    parser.add_argument("--app-dir", default=".", help="application directory to write into")
    parser.add_argument("--account-id", default=None, help="use oauth_token_<account-id>")
    parser.add_argument("--token-file")
    parser.add_argument("--env-name", default=".env.subsurf")
    parser.add_argument("--no-examples", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="print env/integration instructions without writing files",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    plan = build_attach_plan(
        args.app_dir,
        account_id=args.account_id,
        token_file=args.token_file,
        env_name=args.env_name,
        write_examples=not args.no_examples,
    )
    if args.print_only:
        print_attach_instructions(plan)
        return 0

    written = write_attach_files(plan, overwrite=args.overwrite)
    for path in written:
        print(f"wrote {path}")
    print_attach_instructions(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
