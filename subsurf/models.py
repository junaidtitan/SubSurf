"""Claude model catalog and alias resolution for SubSurf."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
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


def openai_model_entries() -> list[dict[str, object]]:
    return [
        {
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "subsurf",
        }
        for model_id in model_ids(include_aliases=True, provider_prefix="subsurf/")
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List SubSurf Claude model aliases")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = [asdict(model) for model in CLAUDE_MODELS]
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

