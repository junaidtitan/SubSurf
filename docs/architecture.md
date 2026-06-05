# Architecture

SubSurf has separate provider paths for Claude Code and Codex/OpenAI-backed
apps. The Claude path publishes Anthropic bearer tokens. The Codex path owns an
isolated Codex home and lets apps run against that home.

## 1. Claude Code Session Bridge

`scripts/cc_session_bridge.py` runs on the macOS host. For SubSurf setup, it
reads the Claude Code OAuth credential blob from an isolated Claude config
Keychain service:

```text
service = Claude Code-credentials-<sha256(config_dir)[:8]>
payload = {"claudeAiOauth": {accessToken, refreshToken, expiresAt, ...}}
```

The normal Claude Code Keychain service is:

```text
Claude Code-credentials
```

Direct bridge commands refuse that shared service unless explicitly run with
`--allow-shared-claude-config`. This prevents pre-isolation state from
refreshing or invalidating the user's normal Claude Code session.

The bridge refreshes credentials against:

```text
https://platform.claude.com/v1/oauth/token
client_id = 9d1c250a-e61b-44d9-88ed-5944d1962f5e
grant_type = refresh_token
```

For setup and wizard flows, refreshed account state and token files are published
under `~/.config/subsurf/installs/<account-id>/`.

## 2. Token Files And Pool

Single local token:

```text
~/.config/subsurf/installs/<account-id>/oauth_token
```

Multi-account store:

```text
~/.config/subsurf/installs/<account-id>/cc_accounts.json
~/.config/subsurf/installs/<account-id>/oauth_token_<id>
```

Fleet pool:

```text
~/.config/subsurf/oauth_pool.json
```

`scripts/oauth_pool.py` assigns tokens to VMs and pushes the active token to:

```text
~/.config/subsurf/oauth_token
```

on each remote VM.

## 3. Runtime Piggyback

`subsurf.anthropic_oauth.AnthropicOAuthClient` reads the token file and builds:

```python
anthropic.AsyncAnthropic(auth_token=token)
```

That sends:

```text
Authorization: Bearer <access token>
```

It also presents the Claude Code request identity by default:

```text
system[0] = "You are Claude Code, Anthropic's official CLI for Claude."
anthropic-beta = oauth-2025-04-20,claude-code-20250219
User-Agent = claude-cli/2.1.81 (external, cli)
```

Disable that with:

```bash
SUBSURF_OAUTH_SPOOF=0
```

## 4. LiteLLM Provider

`subsurf.litellm_provider.SubSurfLiteLLM` adapts the same OAuth client to
LiteLLM's custom-provider interface:

```python
import litellm

from subsurf.litellm_provider import register_subsurf_provider

register_subsurf_provider()
response = litellm.completion(
    model="subsurf/claude-sonnet-4-6",
    messages=[{"role": "user", "content": "hello"}],
)
```

Supported today:

```text
sync completion
async completion
text and data-URL image messages handled by AnthropicOAuthClient
Anthropic thinking parameter passthrough
```

Unsupported parameters fail fast for now:

```text
streaming, tools, tool_choice, functions, response_format, stop
```

## 5. Local Gateway

`subsurf.gateway` exposes the SubSurf OAuth client over a small HTTP surface:

```text
GET  /health
GET  /subsurf/status
GET  /v1/models
POST /v1/chat/completions
POST /v1/messages
```

The gateway supports Claude Code-style model aliases:

```text
opus   -> claude-opus-4-8
sonnet -> claude-sonnet-4-6
haiku  -> claude-haiku-4-5-20251001
```

It also passes through unknown full model IDs, so newly available Claude models
can be tested before the local catalog is updated.

## 6. Codex Login Provider

`subsurf.codex_auth` manages Codex as its own login provider. It uses Codex's
supported isolation boundary:

```text
CODEX_HOME
```

SubSurf creates this per install:

```text
~/.config/subsurf/installs/<account-id>/codex_home/
```

and writes:

```toml
cli_auth_credentials_store = "file"
```

to:

```text
~/.config/subsurf/installs/<account-id>/codex_home/config.toml
```

That forces Codex credentials into:

```text
~/.config/subsurf/installs/<account-id>/codex_home/auth.json
```

instead of the normal `~/.codex` home or keyring-backed default session.

The implementation is based on the current Codex source:

- `CODEX_HOME` controls config/state root.
- `cli_auth_credentials_store = "file"` stores credentials in `auth.json`.
- `auth.json` can represent API-key auth, ChatGPT OAuth tokens, or agent
  identity access-token auth.
- `codex login` supports browser login, device auth, API key via stdin, and
  access token via stdin.

SubSurf exposes:

```bash
subsurf-codex login
subsurf-codex login --device-auth
subsurf-codex models --aliases
subsurf-codex status
subsurf-codex token
subsurf-codex attach --app-dir /path/to/app
```

Model selection is written into the isolated Codex config:

```toml
model = "gpt-5.5"
cli_auth_credentials_store = "file"
```

`subsurf.model_discovery` handles account-scoped model discovery and cache
fallback. API-key Codex auth uses OpenAI's `/v1/models` route. ChatGPT/Codex
auth uses Codex's ChatGPT backend model route. The offline catalog in
`subsurf.openai_models` is only an alias/fallback layer, and explicit ids still
pass through so new model access is not blocked by the local catalog.

The Codex provider does not convert Codex/ChatGPT tokens into Claude tokens, and
it does not claim a ChatGPT access token is an OpenAI Platform API key. Apps
must use the credential with the matching OpenAI/Codex surface.

## Throttle And Recovery

The runtime handles throttles this way:

```text
OAuth call fails with 429/auth/usage limit
  -> subsurf.throttle.classify_oauth_error()
  -> write ~/.config/subsurf/throttled.flag
  -> back off for transient rate_limit
  -> reload token once for rotatable auth/usage conditions
  -> if still exhausted, request fallback or fail
```

The host watcher handles the VM side:

```text
scripts/oauth_pool.py watch
  -> polls ~/.config/subsurf/throttled.flag on each VM
  -> marks current token cooling
  -> assigns reserve token
  -> pushes new ~/.config/subsurf/oauth_token
```

If all OAuth tokens are exhausted, the host can grant bounded API-key fallback:

```bash
python scripts/oauth_pool.py grant-fallback --vm vm0 --duration 1800 --max-uses 20
```

The runtime will only honor the grant if:

```bash
SUBSURF_OAUTH_ALLOW_API_KEY_FALLBACK=true
```

is also set.
