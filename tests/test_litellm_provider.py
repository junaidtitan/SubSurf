from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from subsurf.anthropic_oauth import Choice, Message, Response, Usage
from subsurf.config import SubSurfSettings
from subsurf.litellm_provider import SubSurfLiteLLM, register_subsurf_provider


class FakeOAuthClient:
    def __init__(self, text: str = "provider ok") -> None:
        self.text = text
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
            choices=[Choice(message=Message(content=self.text))],
            usage=Usage(prompt_tokens=10, completion_tokens=20),
        )


@pytest.fixture
def settings(tmp_path: Path) -> SubSurfSettings:
    return SubSurfSettings(oauth_token_path=str(tmp_path / "oauth_token"))


@pytest.fixture
def litellm_globals():
    import litellm

    original_map = list(litellm.custom_provider_map)
    original_custom = list(litellm._custom_providers)
    original_provider_list = list(litellm.provider_list)
    try:
        yield
    finally:
        litellm.custom_provider_map[:] = original_map
        litellm._custom_providers[:] = original_custom
        litellm.provider_list[:] = original_provider_list


@pytest.mark.asyncio
async def test_acompletion_returns_litellm_model_response(settings: SubSurfSettings):
    fake = FakeOAuthClient()
    handler = SubSurfLiteLLM(settings=settings, client_factory=lambda _: fake)

    response = await handler.acompletion(
        model="subsurf/claude-test",
        messages=[{"role": "user", "content": "hi"}],
        api_base="",
        custom_prompt_dict={},
        model_response=_model_response(),
        print_verbose=lambda *args, **kwargs: None,
        encoding=None,
        api_key=None,
        logging_obj=None,
        optional_params={
            "max_tokens": 321,
            "temperature": 0.25,
            "thinking": {"type": "enabled", "budget_tokens": 100},
        },
    )

    assert response.model == "subsurf/claude-test"
    assert response.choices[0].message.content == "provider ok"
    assert response.usage.prompt_tokens == 10
    assert response.usage.completion_tokens == 20
    assert response.usage.total_tokens == 30
    assert fake.calls[0]["temperature"] == 0.25
    assert fake.calls[0]["max_tokens"] == 321
    assert fake.calls[0]["extra"]["thinking"]["budget_tokens"] == 100


def test_completion_sync_path(settings: SubSurfSettings):
    fake = FakeOAuthClient("sync ok")
    handler = SubSurfLiteLLM(settings=settings, client_factory=lambda _: fake)

    response = handler.completion(
        model="subsurf/claude-test",
        messages=[{"role": "user", "content": "hi"}],
        api_base="",
        custom_prompt_dict={},
        model_response=_model_response(),
        print_verbose=lambda *args, **kwargs: None,
        encoding=None,
        api_key=None,
        logging_obj=None,
        optional_params={},
    )

    assert response.choices[0].message.content == "sync ok"
    assert fake.calls[0]["max_tokens"] == settings.max_tokens


def test_register_subsurf_provider_with_litellm(
    settings: SubSurfSettings,
    litellm_globals,
):
    import litellm

    fake = FakeOAuthClient("registered ok")
    register_subsurf_provider(
        handler=SubSurfLiteLLM(settings=settings, client_factory=lambda _: fake),
    )

    response = litellm.completion(
        model="subsurf/claude-test",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=64,
        temperature=0.1,
    )

    assert response.choices[0].message.content == "registered ok"
    assert fake.calls[0]["model"].endswith("claude-test")
    assert fake.calls[0]["max_tokens"] == 64


@pytest.mark.asyncio
async def test_rejects_unsupported_params(settings: SubSurfSettings):
    handler = SubSurfLiteLLM(settings=settings, client_factory=lambda _: FakeOAuthClient())

    with pytest.raises(Exception, match="tools"):
        await handler.acompletion(
            model="subsurf/claude-test",
            messages=[{"role": "user", "content": "hi"}],
            api_base="",
            custom_prompt_dict={},
            model_response=_model_response(),
            print_verbose=lambda *args, **kwargs: None,
            encoding=None,
            api_key=None,
            logging_obj=None,
            optional_params={"tools": [{"type": "function", "function": {"name": "x"}}]},
        )


def test_streaming_is_explicitly_unsupported(settings: SubSurfSettings):
    handler = SubSurfLiteLLM(settings=settings, client_factory=lambda _: FakeOAuthClient())

    with pytest.raises(Exception, match="streaming"):
        handler.streaming()


def _model_response():
    from litellm.types.utils import ModelResponse

    return ModelResponse()

