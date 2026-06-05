# SubSurf

SubSurf is a standalone extraction of local subscription-login piggyback paths:

- Read Claude Code OAuth sessions from macOS Keychain.
- Keep access tokens fresh with refresh-token rotation.
- Publish token files for local processes or VM fleets.
- Call Anthropic with `Authorization: Bearer <OAuth token>`.
- Run Codex login inside an isolated `CODEX_HOME` for OpenAI/Codex-backed apps.
- Register as a LiteLLM custom provider named `subsurf`.
- Serve a small local OpenAI/Anthropic-compatible gateway.
- Present requests with Claude Code identity headers/system block.
- Signal throttles through files so a host-side pool watcher can rotate tokens.

It is intentionally small and separate from Pilot.

## Layout

```text
subsurf/
  anthropic_oauth.py      # bearer-token Anthropic client + Claude Code spoof
  codex_auth.py           # isolated CODEX_HOME login/status/token helpers
  litellm_provider.py     # LiteLLM custom provider for model="subsurf/..."
  litellm_smoke.py        # manual LiteLLM smoke test CLI
  gateway.py              # small local HTTP gateway
  models.py               # Claude model catalog and aliases
  openai_models.py        # GPT/Codex model catalog and aliases
  model_discovery.py      # account-scoped model discovery and cache helpers
  setup.py                # plain terminal setup flow
  qa.py                   # local smoke/adversarial QA runner
  throttle.py             # throttle classification, flag/request/grant files
  engine.py               # small runtime wrapper around the OAuth client
  config.py               # SUBSURF_* settings
  events.py               # lightweight async event bus
scripts/
  cc_session_bridge.py    # host Keychain refresh / publish daemon
  oauth_pool.py           # host VM token pool and watcher
docs/
  architecture.md         # end-to-end flow
  codex-login-provider.md # research and design for isolated Codex login
  gateway.md              # local gateway API
  qa.md                   # unit, smoke, and adversarial QA plan
  wizard.md               # guided setup and app attachment
```

## Quick Start

Install SubSurf from this repo:

```bash
cd SubSurf
python -m pip install -e '.[dev]'
```

Run Claude Code setup:

```bash
subsurf-setup
```

or, without relying on the console script:

```bash
python -m subsurf.setup
```

When Claude Code opens, run:

```text
/login
/exit
```

Finish browser auth between those two commands. Setup then enrolls the token,
starts keepalive, writes `./sample-app`, and runs live Python and gateway
piggyback checks.

Repeatable piggyback test:

```bash
python -m subsurf.demo
```

Expected success lines:

```text
OK: Python app can piggyback
OK: local gateway can piggyback
```

Check setup status:

```bash
subsurf-wizard --status
```

SubSurf automatically creates a stable local account id like
`subsurf-4f1a2b3c`, stores it in `~/.config/subsurf/install_id`, and uses:

```text
~/.claude-subsurf-<account-id>
~/.config/subsurf/installs/<account-id>/
```

Safety rules:

- Only run `/login` in the Claude session that SubSurf setup opens.
- Do not run `/login` in your normal Claude Code terminal for SubSurf setup.
- Avoid `~/.claude` unless you intentionally pass `--allow-shared-claude-config`.
- Direct bridge commands refuse the normal `~/.claude` Keychain service unless
  explicitly overridden.

## Codex Login Provider

SubSurf can also manage a separate Codex login for apps that should run with a
SubSurf-owned Codex identity:

```bash
subsurf-setup --provider codex
```

or:

```bash
python -m subsurf.setup --provider codex
```

The direct wizard supports the same provider split:

```bash
subsurf-wizard --provider claude
subsurf-wizard --provider codex
```

This creates:

```text
~/.config/subsurf/installs/<account-id>/codex_home/
~/.config/subsurf/installs/<account-id>/codex_home/config.toml
~/.config/subsurf/installs/<account-id>/codex_home/auth.json
```

The generated Codex config forces:

```toml
cli_auth_credentials_store = "file"
```

That keeps credentials inside the isolated `CODEX_HOME` instead of using the
user's normal `~/.codex` or keyring-backed Codex session.

Useful commands:

```bash
subsurf-codex login
subsurf-codex login --device-auth
subsurf-codex models --aliases
subsurf-codex status
subsurf-codex env
subsurf-codex token
subsurf-codex attach --app-dir /path/to/app
```

Default Codex model selection starts at `gpt-5.5`, then setup tries to discover
the models available to the isolated account. If no explicit model was requested,
SubSurf rewrites the isolated Codex config to a discovered account-available
model when needed. You can still choose known aliases or any explicit model id:

```bash
subsurf-setup --provider codex --codex-model gpt-5.4-mini
subsurf-setup --provider codex --codex-model codex
subsurf-codex prepare --model gpt-5.5-pro
```

The local selector is only a fallback and alias layer. Run
`subsurf-codex models --live` after login to query models available to that
isolated account. `subsurf-codex models --aliases` shows offline aliases such
as `codex`, `spark`, `chat`, `mini`, and `latest`.

Codex supports ChatGPT login, API-key login, and Codex access-token login. These
are not the same credential type. `subsurf-codex token` prints the stored
credential explicitly for trusted code, but SubSurf does not relabel a Codex
ChatGPT token as an OpenAI Platform API key.

Advanced/manual wizard:

```bash
python -m subsurf.wizard --manual
```

Use the extracted client:

```python
from subsurf.engine import SubSurfEngine

engine = SubSurfEngine()
text = await engine.complete([{"role": "user", "content": "Say hello."}])
```

Use SubSurf through LiteLLM:

```python
import litellm

from subsurf.litellm_provider import register_subsurf_provider

register_subsurf_provider()
response = litellm.completion(
    model="subsurf/claude-sonnet-4-6",
    messages=[{"role": "user", "content": "Say hello."}],
)
print(response.choices[0].message.content)
```

Smoke-test the LiteLLM provider without a token or network call:

```bash
subsurf-litellm-smoke
```

Run the local QA pack:

```bash
subsurf-qa
```

Run the local HTTP gateway:

```bash
subsurf-gateway --host 127.0.0.1 --port 8765
```

Call it through OpenAI-compatible chat completions:

```bash
curl -s http://127.0.0.1:8765/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"sonnet","messages":[{"role":"user","content":"hello"}]}'
```

Model aliases mirror Claude Code-style families:

```text
opus   -> claude-opus-4-8
sonnet -> claude-sonnet-4-6
haiku  -> claude-haiku-4-5-20251001
```

Default setup token and IPC files live under
`~/.config/subsurf/installs/<account-id>/`.

## Attaching Another App

### Claude/Anthropic Apps

The app does not own refresh. SubSurf owns refresh and keeps a token file current.
Your app should either:

- use `SubSurfEngine`, which reads `SUBSURF_OAUTH_TOKEN_PATH`, or
- read the token file itself and construct an Anthropic SDK client with
  `auth_token=token`.

Generate app-side files:

```bash
subsurf-attach --app-dir /path/to/your/app
```

This writes:

- `.env.subsurf` with `SUBSURF_OAUTH_TOKEN_PATH`, `SUBSURF_REASONING_MODEL`, and
  `SUBSURF_OAUTH_SPOOF`.
- `subsurf_client_example.py` using `SubSurfEngine`.
- `subsurf_direct_anthropic_example.py` showing direct SDK attachment.
- `subsurf_litellm_example.py` showing LiteLLM provider attachment.

The key contract:

```text
subsurf-bridge / subsurf-wizard keepalive -> refreshed token file
your app -> reads SUBSURF_OAUTH_TOKEN_PATH -> sends Bearer auth
```

### Codex/OpenAI Apps

Run:

```bash
subsurf-codex attach --app-dir /path/to/your/app
```

This writes:

- `.env.subsurf.codex` with `SUBSURF_CODEX_HOME`, `SUBSURF_CODEX_AUTH_FILE`,
  `SUBSURF_CODEX_TOKEN_COMMAND`, and `CODEX_HOME`.
- `subsurf_codex_cli_example.py` showing how to run Codex with the isolated
  home.
- `subsurf_codex_token_example.py` showing explicit token retrieval without
  printing the secret.

The key contract:

```text
SubSurf owns isolated CODEX_HOME
Codex login writes auth.json there
your app runs Codex or token-aware code with CODEX_HOME pointing there
```
