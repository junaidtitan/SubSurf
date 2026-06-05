"""Small local OpenAI/Anthropic-compatible gateway for SubSurf."""

from __future__ import annotations

import argparse
import hmac
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, Header, HTTPException, Request
except ImportError as exc:  # pragma: no cover - exercised by missing optional deps
    raise RuntimeError("Install gateway dependencies with `pip install 'subsurf[gateway]'`.") from exc

from subsurf.anthropic_oauth import AnthropicOAuthClient, OAuthTokenMissing, Response
from subsurf.config import SubSurfSettings, get_settings
from subsurf.models import openai_model_entries, resolve_model_id


ClientFactory = Callable[[SubSurfSettings], Any]

UNSUPPORTED_PARAMS = {
    "functions",
    "function_call",
    "parallel_tool_calls",
    "response_format",
    "stop",
    "tool_choice",
    "tools",
}


def create_app(
    *,
    settings: SubSurfSettings | None = None,
    client_factory: ClientFactory | None = None,
) -> FastAPI:
    cfg = settings or get_settings()
    factory = client_factory or _default_client_factory
    client_cache: dict[str, Any] = {}

    app = FastAPI(title="SubSurf Gateway", version="0.1.0")

    def get_client() -> Any:
        if "client" not in client_cache:
            client_cache["client"] = factory(cfg)
        return client_cache["client"]

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "service": "subsurf-gateway"}

    @app.get("/subsurf/status")
    async def status(
        authorization: str | None = Header(default=None),
        x_subsurf_token: str | None = Header(default=None, alias="X-SubSurf-Token"),
    ) -> dict[str, object]:
        _require_auth(cfg, authorization, x_subsurf_token)
        token_path = Path(cfg.oauth_token_path).expanduser()
        token_present = token_path.exists() and bool(token_path.read_text().strip())
        stat = token_path.stat() if token_path.exists() else None
        return {
            "ok": True,
            "token_path": str(token_path),
            "token_present": token_present,
            "token_mtime": stat.st_mtime if stat else None,
            "default_model": cfg.reasoning_model,
            "models": len(openai_model_entries()),
        }

    @app.get("/v1/models")
    async def models(
        authorization: str | None = Header(default=None),
        x_subsurf_token: str | None = Header(default=None, alias="X-SubSurf-Token"),
    ) -> dict[str, object]:
        _require_auth(cfg, authorization, x_subsurf_token)
        return {"object": "list", "data": openai_model_entries()}

    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: Request,
        authorization: str | None = Header(default=None),
        x_subsurf_token: str | None = Header(default=None, alias="X-SubSurf-Token"),
    ) -> dict[str, object]:
        _require_auth(cfg, authorization, x_subsurf_token)
        body = await _read_json_body(request)
        _reject_stream(body)
        _reject_unsupported(body)

        messages = body.get("messages")
        if not isinstance(messages, list):
            raise HTTPException(status_code=400, detail="messages must be a list")

        model = resolve_model_id(str(body.get("model") or cfg.reasoning_model))
        response = await _complete(
            get_client(),
            messages=messages,
            model=model,
            temperature=_temperature(body, cfg),
            max_tokens=_max_tokens(body, cfg),
            extra=_extra_params(body),
        )
        return _openai_response(response, model=model)

    @app.post("/v1/messages")
    async def anthropic_messages(
        request: Request,
        authorization: str | None = Header(default=None),
        x_subsurf_token: str | None = Header(default=None, alias="X-SubSurf-Token"),
    ) -> dict[str, object]:
        _require_auth(cfg, authorization, x_subsurf_token)
        body = await _read_json_body(request)
        _reject_stream(body)
        _reject_unsupported(body)

        messages = body.get("messages")
        if not isinstance(messages, list):
            raise HTTPException(status_code=400, detail="messages must be a list")
        if body.get("system") is not None:
            messages = [{"role": "system", "content": body["system"]}, *messages]

        model = resolve_model_id(str(body.get("model") or cfg.reasoning_model))
        response = await _complete(
            get_client(),
            messages=messages,
            model=model,
            temperature=_temperature(body, cfg),
            max_tokens=_max_tokens(body, cfg),
            extra=_extra_params(body),
        )
        return _anthropic_response(response, model=model)

    return app


def _default_client_factory(settings: SubSurfSettings) -> AnthropicOAuthClient:
    return AnthropicOAuthClient(token_path=os.path.expanduser(settings.oauth_token_path))


async def _read_json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return body


async def _complete(
    client: Any,
    *,
    messages: list[dict[str, Any]],
    model: str,
    temperature: float,
    max_tokens: int,
    extra: dict[str, Any],
) -> Response:
    try:
        return await client.complete(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )
    except OAuthTokenMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _openai_response(response: Response, *, model: str) -> dict[str, object]:
    text = response.choices[0].message.content if response.choices else ""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            },
        ],
        "usage": _usage(response),
    }


def _anthropic_response(response: Response, *, model: str) -> dict[str, object]:
    text = response.choices[0].message.content if response.choices else ""
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
        },
    }


def _usage(response: Response) -> dict[str, int]:
    prompt_tokens = response.usage.prompt_tokens
    completion_tokens = response.usage.completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _temperature(body: dict[str, Any], settings: SubSurfSettings) -> float:
    value = body.get("temperature")
    return settings.temperature if value is None else float(value)


def _max_tokens(body: dict[str, Any], settings: SubSurfSettings) -> int:
    value = body.get("max_tokens")
    if value is None:
        value = body.get("max_completion_tokens")
    return settings.max_tokens if value is None else int(value)


def _extra_params(body: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if body.get("thinking") is not None:
        extra["thinking"] = body["thinking"]
    if body.get("effort") is not None:
        extra["effort"] = body["effort"]
    return extra


def _reject_stream(body: dict[str, Any]) -> None:
    if body.get("stream"):
        raise HTTPException(status_code=400, detail="SubSurf gateway does not support streaming yet")


def _reject_unsupported(body: dict[str, Any]) -> None:
    unsupported = sorted(key for key in UNSUPPORTED_PARAMS if body.get(key) is not None)
    if unsupported:
        raise HTTPException(
            status_code=400,
            detail="unsupported params: " + ", ".join(unsupported),
        )


def _require_auth(
    settings: SubSurfSettings,
    authorization: str | None,
    x_subsurf_token: str | None,
) -> None:
    if not settings.gateway_access_token:
        return
    candidates: list[str] = []
    if authorization and authorization.lower().startswith("bearer "):
        candidates.append(authorization.split(" ", 1)[1])
    if x_subsurf_token:
        candidates.append(x_subsurf_token)
    for candidate in candidates:
        if hmac.compare_digest(settings.gateway_access_token, candidate):
            return
    raise HTTPException(status_code=401, detail="invalid SubSurf gateway access token")


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the SubSurf local gateway")
    parser.add_argument("--host", default=settings.gateway_host)
    parser.add_argument("--port", type=int, default=settings.gateway_port)
    parser.add_argument("--reload", action="store_true", help="enable uvicorn reload")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Install gateway dependencies with `pip install 'subsurf[gateway]'`.") from exc

    uvicorn.run(
        "subsurf.gateway:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
