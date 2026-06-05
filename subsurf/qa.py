"""Local QA runner for SubSurf provider and adversarial edge cases."""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from subsurf.anthropic_oauth import (
    Choice,
    Message,
    OAuthTokenMissing,
    Response,
    Usage,
    load_oauth_token,
    split_system_and_convert,
)
from subsurf.config import SubSurfSettings


@dataclass(frozen=True)
class QACase:
    name: str
    kind: str
    run: Callable[[], None]


class FakeOAuthClient:
    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **extra: Any,
    ) -> Response:
        return Response(
            choices=[Choice(message=Message(content=f"qa ok via {model}"))],
            usage=Usage(prompt_tokens=8, completion_tokens=13),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local SubSurf QA checks")
    parser.add_argument(
        "--only",
        choices=["all", "smoke", "adversarial"],
        default="all",
        help="case group to run",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = _cases()
    if args.only != "all":
        cases = [case for case in cases if case.kind == args.only]

    failures = 0
    for case in cases:
        try:
            case.run()
            print(f"PASS {case.kind:11} {case.name}")
        except Exception as exc:
            failures += 1
            print(f"FAIL {case.kind:11} {case.name}: {type(exc).__name__}: {exc}")

    print(f"\n{len(cases) - failures} passed, {failures} failed")
    return 1 if failures else 0


def _cases() -> list[QACase]:
    return [
        QACase("litellm sync provider mock", "smoke", _litellm_sync_mock),
        QACase("litellm async provider mock", "smoke", _litellm_async_mock),
        QACase("gateway OpenAI chat mock", "smoke", _gateway_openai_mock),
        QACase("gateway model catalog", "smoke", _gateway_model_catalog),
        QACase("missing token file fails clearly", "adversarial", _missing_token_file),
        QACase("empty token file fails clearly", "adversarial", _empty_token_file),
        QACase("unsupported tools fail fast", "adversarial", _unsupported_tools),
        QACase("unsupported streaming fails fast", "adversarial", _unsupported_streaming),
        QACase("gateway auth rejects missing key", "adversarial", _gateway_auth_rejects),
        QACase("malformed role is rejected", "adversarial", _malformed_role),
    ]


def _litellm_sync_mock() -> None:
    with _registered_mock_provider():
        import litellm

        response = litellm.completion(
            model="subsurf/claude-qa",
            messages=[{"role": "user", "content": "qa"}],
            max_tokens=64,
        )
        assert response.choices[0].message.content == "qa ok via claude-qa"


def _litellm_async_mock() -> None:
    async def run() -> None:
        with _registered_mock_provider():
            import litellm

            response = await litellm.acompletion(
                model="subsurf/claude-qa",
                messages=[{"role": "user", "content": "qa"}],
                max_tokens=64,
            )
            assert response.choices[0].message.content == "qa ok via claude-qa"

    asyncio.run(run())


def _missing_token_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "oauth_token"
        try:
            load_oauth_token(missing)
        except OAuthTokenMissing:
            return
        raise AssertionError("missing token did not raise OAuthTokenMissing")


def _empty_token_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        token = Path(tmp) / "oauth_token"
        token.write_text("")
        try:
            load_oauth_token(token)
        except OAuthTokenMissing:
            return
        raise AssertionError("empty token did not raise OAuthTokenMissing")


def _gateway_openai_mock() -> None:
    from fastapi.testclient import TestClient

    from subsurf.gateway import create_app

    app = create_app(
        settings=SubSurfSettings(),
        client_factory=lambda _: FakeOAuthClient(),
    )
    response = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "model": "sonnet",
            "messages": [{"role": "user", "content": "qa"}],
            "max_tokens": 64,
        },
    )
    assert response.status_code == 200
    assert response.json()["model"] == "claude-sonnet-4-6"


def _gateway_model_catalog() -> None:
    from fastapi.testclient import TestClient

    from subsurf.gateway import create_app

    response = TestClient(create_app(settings=SubSurfSettings())).get("/v1/models")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    assert {"subsurf/opus", "subsurf/sonnet", "subsurf/haiku"}.issubset(ids)


def _gateway_auth_rejects() -> None:
    from fastapi.testclient import TestClient

    from subsurf.gateway import create_app

    app = create_app(
        settings=SubSurfSettings(gateway_api_key="secret"),
        client_factory=lambda _: FakeOAuthClient(),
    )
    client = TestClient(app)
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"X-Api-Key": "secret"}).status_code == 200


def _unsupported_tools() -> None:
    async def run() -> None:
        with _registered_mock_provider():
            import litellm

            try:
                await litellm.acompletion(
                    model="subsurf/claude-qa",
                    messages=[{"role": "user", "content": "qa"}],
                    tools=[{"type": "function", "function": {"name": "x"}}],
                )
            except Exception as exc:
                if "tools" in str(exc):
                    return
                raise
            raise AssertionError("tools were not rejected")

    asyncio.run(run())


def _unsupported_streaming() -> None:
    with _registered_mock_provider():
        import litellm

        try:
            litellm.completion(
                model="subsurf/claude-qa",
                messages=[{"role": "user", "content": "qa"}],
                stream=True,
            )
        except Exception as exc:
            if "streaming" in str(exc):
                return
            raise
        raise AssertionError("streaming was not rejected")


def _malformed_role() -> None:
    try:
        split_system_and_convert([{"role": "tool", "content": "bad"}])
    except ValueError as exc:
        if "unsupported message role" in str(exc):
            return
        raise
    raise AssertionError("malformed role was not rejected")


@contextmanager
def _registered_mock_provider():
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

    import litellm

    from subsurf.litellm_provider import SubSurfLiteLLM, register_subsurf_provider

    original_map = list(litellm.custom_provider_map)
    original_custom = list(litellm._custom_providers)
    original_provider_list = list(litellm.provider_list)
    original_suppress_debug_info = litellm.suppress_debug_info
    litellm.suppress_debug_info = True
    settings = SubSurfSettings()
    register_subsurf_provider(
        handler=SubSurfLiteLLM(settings=settings, client_factory=lambda _: FakeOAuthClient()),
    )
    try:
        yield
    finally:
        litellm.custom_provider_map[:] = original_map
        litellm._custom_providers[:] = original_custom
        litellm.provider_list[:] = original_provider_list
        litellm.suppress_debug_info = original_suppress_debug_info


if __name__ == "__main__":
    raise SystemExit(main())
