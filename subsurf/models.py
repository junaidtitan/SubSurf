"""Claude model catalog and alias resolution for SubSurf."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


Family = Literal["haiku", "sonnet", "opus"]


@dataclass(frozen=True)
class ClaudeModel:
    id: str
    family: Family
    name: str
    aliases: tuple[str, ...] = ()
    current: bool = False
    notes: str = ""


CLAUDE_MODELS: tuple[ClaudeModel, ...] = (
    ClaudeModel(
        id="claude-opus-4-8",
        family="opus",
        name="Claude Opus 4.8",
        aliases=("opus",),
        current=True,
        notes="Current Claude Code Opus alias target.",
    ),
    ClaudeModel(
        id="claude-opus-4-7",
        family="opus",
        name="Claude Opus 4.7",
    ),
    ClaudeModel(
        id="claude-opus-4-6",
        family="opus",
        name="Claude Opus 4.6",
    ),
    ClaudeModel(
        id="claude-opus-4-5-20251101",
        family="opus",
        name="Claude Opus 4.5",
    ),
    ClaudeModel(
        id="claude-opus-4-1-20250805",
        family="opus",
        name="Claude Opus 4.1",
        notes="Legacy model; availability depends on the account/surface.",
    ),
    ClaudeModel(
        id="claude-sonnet-4-6",
        family="sonnet",
        name="Claude Sonnet 4.6",
        aliases=("sonnet",),
        current=True,
        notes="Current Claude Code Sonnet alias target.",
    ),
    ClaudeModel(
        id="claude-sonnet-4-5-20250929",
        family="sonnet",
        name="Claude Sonnet 4.5",
        aliases=("claude-sonnet-4-5",),
    ),
    ClaudeModel(
        id="claude-sonnet-4-20250514",
        family="sonnet",
        name="Claude Sonnet 4",
        notes="Legacy model; availability depends on the account/surface.",
    ),
    ClaudeModel(
        id="claude-3-7-sonnet-20250219",
        family="sonnet",
        name="Claude Sonnet 3.7",
        aliases=("claude-3-7-sonnet-latest",),
        notes="Legacy model; availability depends on the account/surface.",
    ),
    ClaudeModel(
        id="claude-3-5-sonnet-20241022",
        family="sonnet",
        name="Claude Sonnet 3.5",
        aliases=("claude-3-5-sonnet-latest",),
        notes="Legacy model; availability depends on the account/surface.",
    ),
    ClaudeModel(
        id="claude-3-5-sonnet-20240620",
        family="sonnet",
        name="Claude Sonnet 3.5 June",
        notes="Legacy model; availability depends on the account/surface.",
    ),
    ClaudeModel(
        id="claude-haiku-4-5-20251001",
        family="haiku",
        name="Claude Haiku 4.5",
        aliases=("haiku", "claude-haiku-4-5"),
        current=True,
        notes="Current Claude Code Haiku-class alias target.",
    ),
    ClaudeModel(
        id="claude-3-5-haiku-20241022",
        family="haiku",
        name="Claude Haiku 3.5",
        aliases=("claude-3-5-haiku-latest",),
        notes="Legacy model; availability depends on the account/surface.",
    ),
    ClaudeModel(
        id="claude-3-haiku-20240307",
        family="haiku",
        name="Claude Haiku 3",
        notes="Legacy model; availability depends on the account/surface.",
    ),
)

PROVIDER_PREFIXES = ("subsurf/", "anthropic_oauth/")


def alias_map() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for model in CLAUDE_MODELS:
        aliases[model.id.lower()] = model.id
        for alias in model.aliases:
            aliases[alias.lower()] = model.id
    return aliases


def strip_provider_prefix(model: str) -> str:
    for prefix in PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return model.split("/", 1)[1]
    return model


def resolve_model_id(model: str) -> str:
    """Resolve Claude Code-style aliases while allowing new full IDs through."""
    stripped = strip_provider_prefix(model.strip())
    return alias_map().get(stripped.lower(), stripped)


def supports_sampling(model: str) -> bool:
    """Return False for model IDs known to reject temperature/top_p/top_k."""
    resolved = resolve_model_id(model)
    match = re.fullmatch(r"claude-opus-4-(\d+)(?:-\d{8})?", resolved)
    if match and int(match.group(1)) >= 7:
        return False
    return True


def model_ids(*, include_aliases: bool = False, provider_prefix: str = "") -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for model in CLAUDE_MODELS:
        values = [model.id]
        if include_aliases:
            values.extend(model.aliases)
        for value in values:
            key = provider_prefix + value
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def static_openai_model_entries() -> list[dict[str, object]]:
    return [
        {
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "subsurf",
        }
        for model_id in model_ids(include_aliases=True, provider_prefix="subsurf/")
    ]


def openai_model_entries(
    *,
    token_path: str | Path | None = None,
    cache_file: str | Path | None = None,
) -> list[dict[str, object]]:
    static_entries = static_openai_model_entries()
    if token_path is None:
        return static_entries

    from subsurf import model_discovery

    cache = cache_file or Path(token_path).expanduser().parent / "claude_models.json"
    try:
        discovered = model_discovery.discover_anthropic_models(
            token_path,
            cache_file=cache,
        )
    except Exception:
        try:
            discovered = model_discovery.read_model_cache(cache)
        except Exception:
            discovered = []

    if not discovered:
        return static_entries

    dynamic_entries = model_discovery.openai_entries(discovered, prefix="subsurf/")
    return model_discovery.merge_model_entries(dynamic_entries, static_entries)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List SubSurf Claude model aliases")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--live", action="store_true", help="query models available to this token")
    parser.add_argument("--token-file", default="~/.config/subsurf/oauth_token")
    parser.add_argument("--cache-file")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = [asdict(model) for model in CLAUDE_MODELS]
    if args.live:
        entries = openai_model_entries(
            token_path=args.token_file,
            cache_file=args.cache_file,
        )
        if args.json:
            print(json.dumps({"object": "list", "data": entries}, indent=2))
        else:
            for entry in entries:
                print(entry["id"])
        return 0

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    for model in CLAUDE_MODELS:
        aliases = ", ".join(model.aliases) if model.aliases else "-"
        marker = "current" if model.current else "known"
        print(f"{model.id:34} {model.family:6} {marker:7} aliases={aliases}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
