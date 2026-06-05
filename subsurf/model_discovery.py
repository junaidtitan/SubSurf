"""Account-scoped model discovery with static fallback support."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from subsurf.anthropic_oauth import anthropic_oauth_headers, load_oauth_token


OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
CHATGPT_CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"

HttpGet = Callable[[str, Mapping[str, str], float], Mapping[str, Any]]


class ModelDiscoveryError(RuntimeError):
    """Raised when account-scoped model discovery cannot complete."""


@dataclass(frozen=True)
class DiscoveredModel:
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "account"
    display_name: str | None = None

    def as_openai_entry(self, *, prefix: str = "") -> dict[str, object]:
        entry: dict[str, object] = {
            "id": prefix + self.id,
            "object": self.object,
            "created": self.created,
            "owned_by": self.owned_by,
        }
        if self.display_name:
            entry["display_name"] = self.display_name
        return entry


def default_http_get(url: str, headers: Mapping[str, str], timeout: float) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ModelDiscoveryError(f"model discovery failed for {url}: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelDiscoveryError(f"model discovery response from {url} was not a JSON object")
    return data


def parse_model_payload(payload: Mapping[str, Any], *, owner: str) -> list[DiscoveredModel]:
    raw_models = payload.get("data")
    if raw_models is None:
        raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        raise ModelDiscoveryError("model discovery response did not include a model list")

    models: list[DiscoveredModel] = []
    seen: set[str] = set()
    for item in raw_models:
        model = parse_model_item(item, owner=owner)
        if model is None or model.id in seen:
            continue
        models.append(model)
        seen.add(model.id)
    return models


def parse_model_item(item: Any, *, owner: str) -> DiscoveredModel | None:
    if isinstance(item, str):
        return DiscoveredModel(id=item, owned_by=owner)
    if not isinstance(item, dict):
        return None
    model_id = item.get("id") or item.get("slug") or item.get("name")
    if not model_id:
        return None
    created = item.get("created")
    return DiscoveredModel(
        id=str(model_id),
        object=str(item.get("object") or "model"),
        created=created if isinstance(created, int) else 0,
        owned_by=str(item.get("owned_by") or owner),
        display_name=optional_str(item.get("display_name") or item.get("name")),
    )


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def write_model_cache(
    cache_file: str | Path,
    *,
    provider: str,
    models: Sequence[DiscoveredModel],
) -> None:
    path = Path(cache_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": provider,
        "fetched_at": int(time.time()),
        "data": [model.as_openai_entry() for model in models],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


def read_model_cache(cache_file: str | Path, *, owner: str = "cached") -> list[DiscoveredModel]:
    path = Path(cache_file).expanduser()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ModelDiscoveryError(f"model cache is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ModelDiscoveryError(f"model cache must contain a JSON object: {path}")
    return parse_model_payload(payload, owner=owner)


def discover_openai_models(
    api_key: str,
    *,
    url: str = OPENAI_MODELS_URL,
    cache_file: str | Path | None = None,
    http_get: HttpGet = default_http_get,
    timeout: float = 5.0,
) -> list[DiscoveredModel]:
    headers = {"Authorization": f"Bearer {api_key}"}
    models = parse_model_payload(http_get(url, headers, timeout), owner="openai")
    if cache_file:
        write_model_cache(cache_file, provider="openai", models=models)
    return models


def discover_chatgpt_codex_models(
    access_token: str,
    *,
    account_id: str | None = None,
    url: str = CHATGPT_CODEX_MODELS_URL,
    cache_file: str | Path | None = None,
    http_get: HttpGet = default_http_get,
    timeout: float = 5.0,
) -> list[DiscoveredModel]:
    headers = {"Authorization": f"Bearer {access_token}"}
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    models = parse_model_payload(http_get(url, headers, timeout), owner="chatgpt")
    if cache_file:
        write_model_cache(cache_file, provider="chatgpt-codex", models=models)
    return models


def discover_anthropic_models(
    token_path: str | Path,
    *,
    url: str = ANTHROPIC_MODELS_URL,
    cache_file: str | Path | None = None,
    http_get: HttpGet = default_http_get,
    timeout: float = 5.0,
) -> list[DiscoveredModel]:
    token = load_oauth_token(token_path)
    models = parse_model_payload(
        http_get(url, anthropic_oauth_headers(token), timeout),
        owner="anthropic",
    )
    if cache_file:
        write_model_cache(cache_file, provider="anthropic", models=models)
    return models


def openai_entries(models: Sequence[DiscoveredModel], *, prefix: str = "") -> list[dict[str, object]]:
    return [model.as_openai_entry(prefix=prefix) for model in models]


def merge_model_entries(*groups: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[str] = set()
    for group in groups:
        for entry in group:
            model_id = entry.get("id")
            if not isinstance(model_id, str) or model_id in seen:
                continue
            merged.append(dict(entry))
            seen.add(model_id)
    return merged
