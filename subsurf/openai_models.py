"""OpenAI/Codex model catalog and aliases for SubSurf."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class OpenAIModel:
    id: str
    family: str
    name: str
    aliases: tuple[str, ...] = ()
    current: bool = False
    notes: str = ""


OPENAI_MODELS: tuple[OpenAIModel, ...] = (
    OpenAIModel(
        id="gpt-5.5",
        family="gpt",
        name="GPT-5.5",
        aliases=("latest", "flagship", "best"),
        current=True,
        notes="Current flagship model for complex reasoning and coding.",
    ),
    OpenAIModel(
        id="gpt-5.5-pro",
        family="gpt",
        name="GPT-5.5 pro",
        aliases=("pro", "best-pro"),
        current=True,
        notes="Higher-compute GPT-5.5 variant.",
    ),
    OpenAIModel(
        id="gpt-5.4",
        family="gpt",
        name="GPT-5.4",
        aliases=("balanced",),
        current=True,
        notes="More affordable frontier model for coding and professional work.",
    ),
    OpenAIModel(
        id="gpt-5.4-pro",
        family="gpt",
        name="GPT-5.4 pro",
        current=True,
        notes="Higher-compute GPT-5.4 variant.",
    ),
    OpenAIModel(
        id="gpt-5.4-mini",
        family="gpt",
        name="GPT-5.4 mini",
        aliases=("mini", "fast"),
        current=True,
        notes="Lower-latency, lower-cost GPT-5.4-class model.",
    ),
    OpenAIModel(
        id="gpt-5.4-nano",
        family="gpt",
        name="GPT-5.4 nano",
        aliases=("nano", "cheap"),
        current=True,
        notes="Cheapest GPT-5.4-class model.",
    ),
    OpenAIModel(
        id="gpt-5.3-codex-spark",
        family="codex",
        name="GPT-5.3 Codex Spark",
        aliases=("spark",),
        current=True,
        notes="Research-preview Codex model optimized for near-instant coding iteration.",
    ),
    OpenAIModel(
        id="gpt-5.3-codex",
        family="codex",
        name="GPT-5.3 Codex",
        aliases=("codex", "coding"),
        current=True,
        notes="Current Codex-specialized API model for agentic coding tasks.",
    ),
    OpenAIModel(
        id="gpt-5.2-codex",
        family="codex",
        name="GPT-5.2 Codex",
        notes="Previous Codex-specialized model for long-horizon coding tasks.",
    ),
    OpenAIModel(
        id="gpt-5.1-codex",
        family="codex",
        name="GPT-5.1 Codex",
        aliases=("codex-5.1",),
        notes="Previous Codex-specialized model surfaced through Responses-compatible workflows.",
    ),
    OpenAIModel(
        id="gpt-5.1-codex-max",
        family="codex",
        name="GPT-5.1 Codex Max",
        notes="Previous Codex model optimized for long-running tasks.",
    ),
    OpenAIModel(
        id="gpt-5.1-codex-mini",
        family="codex",
        name="GPT-5.1 Codex mini",
        notes="Previous smaller Codex-specialized model.",
    ),
    OpenAIModel(
        id="gpt-5-codex",
        family="codex",
        name="GPT-5 Codex",
        notes="Previous GPT-5 Codex-specialized model.",
    ),
    OpenAIModel(
        id="codex-mini-latest",
        family="codex",
        name="Codex mini latest",
        notes="Deprecated fast reasoning model optimized for the Codex CLI.",
    ),
    OpenAIModel(
        id="gpt-5.3-chat-latest",
        family="chat",
        name="GPT-5.3 Chat",
        aliases=("instant",),
        current=True,
        notes="ChatGPT instant model.",
    ),
    OpenAIModel(
        id="gpt-5.2-chat-latest",
        family="chat",
        name="GPT-5.2 Chat",
        notes="Previous ChatGPT model.",
    ),
    OpenAIModel(
        id="gpt-5.1-chat-latest",
        family="chat",
        name="GPT-5.1 Chat",
        notes="Previous ChatGPT model.",
    ),
    OpenAIModel(
        id="gpt-5-chat-latest",
        family="chat",
        name="GPT-5 Chat",
        notes="Previous ChatGPT model.",
    ),
    OpenAIModel(
        id="chat-latest",
        family="chat",
        name="Chat latest",
        aliases=("chat", "chat-latest"),
        current=True,
        notes="Latest instant model used in ChatGPT where available.",
    ),
    OpenAIModel(
        id="gpt-5.2",
        family="gpt",
        name="GPT-5.2",
        notes="Previous frontier model.",
    ),
    OpenAIModel(
        id="gpt-5.2-pro",
        family="gpt",
        name="GPT-5.2 pro",
        notes="Previous pro frontier model.",
    ),
    OpenAIModel(
        id="gpt-5.1",
        family="gpt",
        name="GPT-5.1",
        notes="Previous coding and agentic-task model.",
    ),
    OpenAIModel(
        id="gpt-5",
        family="gpt",
        name="GPT-5",
        notes="Previous GPT-5 generation.",
    ),
    OpenAIModel(
        id="gpt-5-pro",
        family="gpt",
        name="GPT-5 pro",
        notes="Previous higher-compute GPT-5 model.",
    ),
    OpenAIModel(
        id="gpt-5-mini",
        family="gpt",
        name="GPT-5 mini",
        notes="Cost-sensitive GPT-5 variant.",
    ),
    OpenAIModel(
        id="gpt-5-nano",
        family="gpt",
        name="GPT-5 nano",
        notes="Smallest GPT-5 variant.",
    ),
    OpenAIModel(
        id="gpt-4.1",
        family="gpt",
        name="GPT-4.1",
        notes="Non-reasoning GPT model.",
    ),
    OpenAIModel(
        id="gpt-4.1-mini",
        family="gpt",
        name="GPT-4.1 mini",
        notes="Smaller GPT-4.1 variant.",
    ),
    OpenAIModel(
        id="gpt-4.1-nano",
        family="gpt",
        name="GPT-4.1 nano",
        notes="Smallest GPT-4.1 variant.",
    ),
    OpenAIModel(
        id="gpt-4o",
        family="gpt",
        name="GPT-4o",
        notes="Previous fast multimodal GPT model.",
    ),
    OpenAIModel(
        id="gpt-4o-mini",
        family="gpt",
        name="GPT-4o mini",
        notes="Previous small GPT-4o model.",
    ),
    OpenAIModel(
        id="gpt-4o-search-preview",
        family="gpt",
        name="GPT-4o Search Preview",
        notes="Deprecated GPT model for web search in Chat Completions.",
    ),
    OpenAIModel(
        id="gpt-4o-mini-search-preview",
        family="gpt",
        name="GPT-4o mini Search Preview",
        notes="Deprecated fast, affordable GPT model for web search.",
    ),
    OpenAIModel(
        id="gpt-4.5-preview",
        family="gpt",
        name="GPT-4.5 Preview",
        notes="Deprecated large GPT model.",
    ),
    OpenAIModel(
        id="gpt-4-turbo",
        family="gpt",
        name="GPT-4 Turbo",
        notes="Deprecated older high-intelligence GPT model.",
    ),
    OpenAIModel(
        id="gpt-4-turbo-preview",
        family="gpt",
        name="GPT-4 Turbo Preview",
        notes="Deprecated older fast GPT model.",
    ),
    OpenAIModel(
        id="gpt-4",
        family="gpt",
        name="GPT-4",
        notes="Deprecated older high-intelligence GPT model.",
    ),
    OpenAIModel(
        id="gpt-3.5-turbo",
        family="gpt",
        name="GPT-3.5 Turbo",
        notes="Deprecated legacy GPT model for cheaper chat and non-chat tasks.",
    ),
    OpenAIModel(
        id="chatgpt-4o-latest",
        family="chat",
        name="ChatGPT-4o",
        notes="Deprecated GPT-4o model used in ChatGPT.",
    ),
)

DEFAULT_CODEX_MODEL = "gpt-5.5"
PROVIDER_PREFIXES = ("openai/", "codex/", "subsurf-codex/")


def _aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for model in OPENAI_MODELS:
        aliases[model.id.lower()] = model.id
        for alias in model.aliases:
            aliases[alias.lower()] = model.id
    return aliases


ALIASES = _aliases()


def strip_provider_prefix(model: str) -> str:
    for prefix in PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return model.split("/", 1)[1]
    return model


def resolve_model_id(model: str | None) -> str:
    """Resolve common aliases while allowing newly available full IDs through."""
    if not model:
        return DEFAULT_CODEX_MODEL
    stripped = strip_provider_prefix(model.strip())
    return ALIASES.get(stripped.lower(), stripped)


def model_ids(*, include_aliases: bool = False, provider_prefix: str = "") -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for model in OPENAI_MODELS:
        values = [model.id]
        if include_aliases:
            values.extend(model.aliases)
        for value in values:
            key = provider_prefix + value
            if key not in seen:
                ids.append(key)
                seen.add(key)
    return ids


def choose_available_model(available_ids: list[str], *, requested: str | None = None) -> str:
    available = set(available_ids)
    if requested:
        resolved = resolve_model_id(requested)
        if resolved in available:
            return resolved
        return resolved

    for candidate in (
        DEFAULT_CODEX_MODEL,
        "gpt-5.3-codex",
        "gpt-5.4",
        "gpt-5.4-mini",
    ):
        if candidate in available:
            return candidate
    if available_ids:
        return available_ids[0]
    return DEFAULT_CODEX_MODEL


def rows() -> list[dict[str, object]]:
    return [asdict(model) for model in OPENAI_MODELS]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List SubSurf Codex/OpenAI model aliases")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--aliases", action="store_true", help="include aliases")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.json:
        import json

        print(json.dumps(rows(), indent=2))
        return 0

    for model in OPENAI_MODELS:
        aliases = ", ".join(model.aliases) if model.aliases else "-"
        marker = "current" if model.current else "known"
        print(f"{model.id:24} {model.family:6} {marker:7} aliases={aliases}")
    if args.aliases:
        print()
        print("All selectable ids:")
        for model_id in model_ids(include_aliases=True):
            print(model_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
