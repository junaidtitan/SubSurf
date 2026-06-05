"""Manual smoke test for the SubSurf LiteLLM provider."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm

from subsurf.anthropic_oauth import Choice, Message, Response, Usage
from subsurf.config import get_settings
from subsurf.litellm_provider import SubSurfLiteLLM, register_subsurf_provider


class MockOAuthClient:
    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **extra: Any,
    ) -> Response:
        prompt = _last_user_text(messages)
        return Response(
            choices=[
                Choice(
                    message=Message(
                        content=(
                            "SubSurf LiteLLM mock response. "
                            f"model={model} max_tokens={max_tokens} prompt={prompt!r}"
                        ),
                    ),
                ),
            ],
            usage=Usage(prompt_tokens=12, completion_tokens=18),
        )


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Smoke test the SubSurf LiteLLM provider")
    parser.add_argument(
        "--model",
        default=f"subsurf/{settings.reasoning_model}",
        help="LiteLLM model name, usually subsurf/<anthropic-model>",
    )
    parser.add_argument(
        "--prompt",
        default="Reply with a short hello from SubSurf through LiteLLM.",
        help="single user prompt to send",
    )
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--live",
        action="store_true",
        help="use the real OAuth token file instead of the offline mock client",
    )
    parser.add_argument(
        "--async-call",
        action="store_true",
        help="exercise litellm.acompletion instead of litellm.completion",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()

    if args.live:
        token_path = Path(settings.oauth_token_path).expanduser()
        if not token_path.exists() or not token_path.read_text().strip():
            print(f"missing OAuth token file: {token_path}")
            print("run `subsurf-setup` or `subsurf-wizard` first")
            return 2
        register_subsurf_provider()
        mode = "live"
    else:
        register_subsurf_provider(
            handler=SubSurfLiteLLM(
                settings=settings,
                client_factory=lambda _: MockOAuthClient(),
            ),
        )
        mode = "mock"

    messages = [{"role": "user", "content": args.prompt}]
    if args.async_call:
        response = asyncio.run(_acomplete(args, messages))
    else:
        response = litellm.completion(
            model=args.model,
            messages=messages,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )

    print("provider: subsurf")
    print(f"mode:     {mode}")
    print(f"model:    {response.model}")
    print(f"content:  {response.choices[0].message.content}")
    if response.usage is not None:
        print(
            "usage:    "
            f"prompt={response.usage.prompt_tokens} "
            f"completion={response.usage.completion_tokens} "
            f"total={response.usage.total_tokens}",
        )
    return 0


async def _acomplete(args: argparse.Namespace, messages: list[dict[str, Any]]) -> Any:
    return await litellm.acompletion(
        model=args.model,
        messages=messages,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
