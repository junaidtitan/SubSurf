from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from subsurf.anthropic_oauth import Choice, Message, Response, Usage
from subsurf.config import SubSurfSettings
from subsurf.gateway import create_app


class FakeOAuthClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **extra: Any,
    ) -> Response:
        self.calls.append({
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra": extra,
        })
        return Response(
            choices=[Choice(message=Message(content=f"gateway ok via {model}"))],
            usage=Usage(prompt_tokens=7, completion_tokens=11),
        )


def test_openai_models_endpoint_includes_family_aliases(tmp_path: Path):
    client = TestClient(_app(tmp_path, FakeOAuthClient()))

    response = client.get("/v1/models")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    assert "subsurf/opus" in ids
    assert "subsurf/sonnet" in ids
    assert "subsurf/haiku" in ids


def test_openai_chat_completion_resolves_alias(tmp_path: Path):
    fake = FakeOAuthClient()
    client = TestClient(_app(tmp_path, fake))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "sonnet",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 128,
            "temperature": 0.2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "claude-sonnet-4-6"
    assert body["choices"][0]["message"]["content"] == "gateway ok via claude-sonnet-4-6"
    assert body["usage"]["total_tokens"] == 18
    assert fake.calls[0]["model"] == "claude-sonnet-4-6"
    assert fake.calls[0]["max_tokens"] == 128
    assert fake.calls[0]["temperature"] == 0.2


def test_anthropic_messages_endpoint_resolves_alias_and_system(tmp_path: Path):
    fake = FakeOAuthClient()
    client = TestClient(_app(tmp_path, fake))

    response = client.post(
        "/v1/messages",
        json={
            "model": "haiku",
            "system": "system prompt",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 64,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["content"][0]["text"] == "gateway ok via claude-haiku-4-5-20251001"
    assert fake.calls[0]["messages"][0] == {"role": "system", "content": "system prompt"}


def test_gateway_rejects_streaming(tmp_path: Path):
    client = TestClient(_app(tmp_path, FakeOAuthClient()))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "sonnet",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert response.status_code == 400
    assert "streaming" in response.json()["detail"]


def test_gateway_rejects_invalid_json(tmp_path: Path):
    client = TestClient(_app(tmp_path, FakeOAuthClient()))

    response = client.post(
        "/v1/chat/completions",
        content="{",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert "valid JSON" in response.json()["detail"]


def test_gateway_rejects_non_object_json(tmp_path: Path):
    client = TestClient(_app(tmp_path, FakeOAuthClient()))

    response = client.post(
        "/v1/chat/completions",
        json=[{"role": "user", "content": "hi"}],
    )

    assert response.status_code == 400
    assert "JSON object" in response.json()["detail"]


def test_gateway_auth_when_configured(tmp_path: Path):
    settings = SubSurfSettings(
        oauth_token_path=str(tmp_path / "oauth_token"),
        gateway_access_token="secret",
    )
    client = TestClient(create_app(settings=settings, client_factory=lambda _: FakeOAuthClient()))

    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert client.get("/v1/models", headers={"X-SubSurf-Token": "secret"}).status_code == 200


def _app(tmp_path: Path, fake: FakeOAuthClient):
    settings = SubSurfSettings(oauth_token_path=str(tmp_path / "oauth_token"))
    return create_app(settings=settings, client_factory=lambda _: fake)
