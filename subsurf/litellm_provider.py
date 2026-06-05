"""LiteLLM custom provider for SubSurf OAuth-backed Anthropic calls."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from litellm import CustomLLM
from litellm.llms.custom_llm import CustomLLMError
from litellm.types.utils import Choices, Message, ModelResponse, Usage

from subsurf.anthropic_oauth import AnthropicOAuthClient, Response
from subsurf.config import SubSurfSettings, get_settings


PROVIDER_NAME = "subsurf"
UNSUPPORTED_OPTIONAL_PARAMS = {
    "functions",
    "function_call",
    "parallel_tool_calls",
    "response_format",
    "stop",
    "tool_choice",
    "tools",
}

ClientFactory = Callable[[SubSurfSettings], Any]


class SubSurfLiteLLM(CustomLLM):
    """LiteLLM adapter for `model="subsurf/<anthropic-model>"` calls."""

    def __init__(
        self,
        settings: SubSurfSettings | None = None,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings or get_settings()
        self._client_factory = client_factory or self._default_client_factory
        self._client: Any | None = None

    def completion(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers={},
        timeout=None,
        client=None,
    ) -> ModelResponse:
        return _run_sync(
            self._complete(
                model=model,
                messages=messages,
                optional_params=optional_params,
                model_response=model_response,
            ),
        )

    async def acompletion(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers={},
        timeout=None,
        client=None,
    ) -> ModelResponse:
        return await self._complete(
            model=model,
            messages=messages,
            optional_params=optional_params,
            model_response=model_response,
        )

    def streaming(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        raise CustomLLMError(
            status_code=400,
            message="SubSurf LiteLLM provider does not support streaming yet.",
        )

    async def astreaming(self, *args: Any, **kwargs: Any) -> Any:
        raise CustomLLMError(
            status_code=400,
            message="SubSurf LiteLLM provider does not support streaming yet.",
        )

    async def _complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        optional_params: dict[str, Any] | None,
        model_response: ModelResponse,
    ) -> ModelResponse:
        params = dict(optional_params or {})
        _reject_unsupported(params)

        temperature = params.pop("temperature", None)
        if temperature is None:
            temperature = self.settings.temperature

        max_tokens = params.pop("max_tokens", None)
        if max_tokens is None:
            max_tokens = params.pop("max_completion_tokens", None)
        if max_tokens is None:
            max_tokens = self.settings.max_tokens

        extra = {}
        if "thinking" in params and params["thinking"] is not None:
            extra["thinking"] = params["thinking"]

        response = await self._get_client().complete(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )
        return to_litellm_response(response, model=model, model_response=model_response)

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(self.settings)
        return self._client

    @staticmethod
    def _default_client_factory(settings: SubSurfSettings) -> AnthropicOAuthClient:
        return AnthropicOAuthClient(token_path=os.path.expanduser(settings.oauth_token_path))


def to_litellm_response(
    response: Response,
    *,
    model: str,
    model_response: ModelResponse | None = None,
) -> ModelResponse:
    """Convert SubSurf's small response object into LiteLLM's response shape."""
    text = response.choices[0].message.content if response.choices else ""
    prompt_tokens = response.usage.prompt_tokens
    completion_tokens = response.usage.completion_tokens
    result = model_response or ModelResponse()
    result.model = model
    result.choices = [
        Choices(
            finish_reason="stop",
            index=0,
            message=Message(content=text, role="assistant"),
        ),
    ]
    result.usage = Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return result


def register_subsurf_provider(
    *,
    provider: str = PROVIDER_NAME,
    handler: SubSurfLiteLLM | None = None,
) -> SubSurfLiteLLM:
    """Register SubSurf in LiteLLM's custom provider map and return the handler."""
    import litellm
    from litellm.utils import custom_llm_setup

    custom_handler = handler or SubSurfLiteLLM()
    for item in litellm.custom_provider_map:
        if item["provider"] == provider:
            item["custom_handler"] = custom_handler
            custom_llm_setup()
            return custom_handler

    litellm.custom_provider_map.append({
        "provider": provider,
        "custom_handler": custom_handler,
    })
    custom_llm_setup()
    return custom_handler


def _reject_unsupported(params: dict[str, Any]) -> None:
    unsupported = sorted(
        key for key in UNSUPPORTED_OPTIONAL_PARAMS
        if key in params and params[key] is not None
    )
    if unsupported:
        raise CustomLLMError(
            status_code=400,
            message=(
                "SubSurf LiteLLM provider does not support these params yet: "
                + ", ".join(unsupported)
            ),
        )


def _run_sync(awaitable: Awaitable[ModelResponse]) -> ModelResponse:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result: dict[str, ModelResponse] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # pragma: no cover - re-raised in caller
            error["value"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["value"]
    return result["value"]


subsurf_litellm = SubSurfLiteLLM()

