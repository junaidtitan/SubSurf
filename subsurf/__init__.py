"""SubSurf: Claude Code and Codex login piggyback utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from subsurf.anthropic_oauth import AnthropicOAuthClient, OAuthTokenMissing
    from subsurf.engine import SubSurfEngine

__all__ = ["AnthropicOAuthClient", "SubSurfEngine", "OAuthTokenMissing"]


def __getattr__(name: str):
    if name in {"AnthropicOAuthClient", "OAuthTokenMissing"}:
        from subsurf.anthropic_oauth import AnthropicOAuthClient, OAuthTokenMissing

        values = {
            "AnthropicOAuthClient": AnthropicOAuthClient,
            "OAuthTokenMissing": OAuthTokenMissing,
        }
        return values[name]
    if name == "SubSurfEngine":
        from subsurf.engine import SubSurfEngine

        return SubSurfEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
