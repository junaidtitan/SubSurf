# SubSurf

SubSurf lets your local apps use an isolated Claude Code or Codex login without
sharing your normal CLI session.

It is a small local bridge for people who already use Claude Code or Codex and
want their own tools, agents, scripts, gateways, or test apps to piggyback on a
separate managed login.

## What SubSurf Does

SubSurf can:

- Walk you through Claude Code or Codex setup from the terminal.
- Keep Claude Code OAuth access tokens fresh with a local keepalive daemon.
- Write safe app attachment files so another project can use the isolated login.
- Run Codex with a separate `CODEX_HOME`, so it does not collide with `~/.codex`.
- Discover available Claude/Codex/OpenAI models from the active account when
  possible, with offline aliases as a fallback.
- Register as a LiteLLM provider named `subsurf`.
- Run a small local OpenAI/Anthropic-compatible gateway.
- Run local smoke and adversarial QA checks.

SubSurf does **not** turn every credential into the same credential type. Claude
OAuth, Codex ChatGPT auth, Codex access tokens, and OpenAI API keys are handled
as separate things.

## Safety Model

The default setup is isolated.

For Claude Code, SubSurf uses a generated config directory like:

```text
~/.claude-subsurf-<account-id>
```

For Codex, SubSurf uses:

```text
~/.config/subsurf/installs/<account-id>/codex_home/
```

The normal user directories are guarded:

```text
~/.claude
~/.codex
```

SubSurf refuses to use those shared locations unless you explicitly pass an
override flag. This matters because logging into a shared CLI profile can affect
your normal Claude Code or Codex session.

## Requirements

- Python 3.11 or newer.
- macOS for the Claude Code OAuth bridge, because Claude Code credentials are
  read from macOS Keychain.
- Claude Code CLI installed if you want the Claude provider.
- Codex CLI installed if you want the Codex provider.

Check the CLIs:

```bash
claude --version
codex --version
```

## Install

From this repository:

```bash
cd /Users/jq/Documents/Advisor/PilotCC/SubSurf
python -m pip install -e '.[dev]'
```

If you prefer a fresh virtual environment:

```bash
cd /Users/jq/Documents/Advisor/PilotCC/SubSurf
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Verify SubSurf imports:

```bash
python -m subsurf.wizard --status
```

## Quick Start

Run the guided CLI wizard:

```bash
python -m subsurf.wizard
```

The wizard clears the visible terminal, explains what SubSurf is, then asks:

```text
[1] Claude Code subscription
[2] Codex subscription
```

Pick the provider and follow the steps.

You can also skip the intro and go directly to a provider:

```bash
python -m subsurf.wizard --provider claude
python -m subsurf.wizard --provider codex
```

Use the plain line-oriented flow instead of the cleared-screen intro:

```bash
python -m subsurf.wizard --no-clear-screen
```

## Claude Code Flow

Start the Claude setup:

```bash
python -m subsurf.wizard --provider claude
```

The wizard will show the isolated config directory it is using, then launch
Claude Code with `CLAUDE_CONFIG_DIR` set to that directory.

Inside the Claude Code session opened by SubSurf:

```text
/login
```

Complete browser authorization, return to Claude Code, then run:

```text
/exit
```

After Claude exits, SubSurf continues:

1. Reads the isolated Claude Code Keychain session.
2. Publishes a token file under `~/.config/subsurf/installs/<account-id>/`.
3. Starts the keepalive daemon, unless disabled.
4. Writes app attachment examples into `sample-app`.

Check status:

```bash
python -m subsurf.wizard --status
```

Important: run `/login` only in the Claude Code session that SubSurf opens. Do
not run it in your normal Claude Code terminal for SubSurf setup.

## Codex Flow

Start the Codex setup:

```bash
python -m subsurf.wizard --provider codex
```

SubSurf creates an isolated `CODEX_HOME` and writes a Codex config containing:

```toml
cli_auth_credentials_store = "file"
```

That makes Codex store credentials in:

```text
~/.config/subsurf/installs/<account-id>/codex_home/auth.json
```

instead of using your normal `~/.codex` or a shared keyring-backed session.

Useful Codex setup variants:

```bash
python -m subsurf.wizard --provider codex --codex-device-auth
python -m subsurf.wizard --provider codex --codex-with-api-key
python -m subsurf.wizard --provider codex --codex-with-access-token
```

After login, list models available to the isolated account:

```bash
subsurf-codex models --live
```

Offline aliases are available without login:

```bash
subsurf-codex models --aliases
```

Pick a model explicitly:

```bash
python -m subsurf.wizard --provider codex --codex-model gpt-5.4-mini
python -m subsurf.wizard --provider codex --codex-model codex
```

If you do not request a model, SubSurf starts from its default and then tries to
select a model actually available on the account.

## App Attachment

SubSurf writes small files that show another app how to use the isolated login.

### Attach A Claude/Anthropic App

Generate attachment files:

```bash
subsurf-attach --app-dir /path/to/your/app
```

This writes:

```text
.env.subsurf
subsurf_client_example.py
subsurf_direct_anthropic_example.py
subsurf_litellm_example.py
```

The app-side contract is:

```text
SubSurf keepalive refreshes the token file.
Your app reads SUBSURF_OAUTH_TOKEN_PATH.
Your app sends Anthropic Bearer auth with that token.
```

Minimal Python usage:

```python
from subsurf import SubSurfEngine

text = await SubSurfEngine().complete([
    {"role": "user", "content": "Reply with hello."},
])
```

Direct Anthropic SDK usage:

```python
from pathlib import Path
import os

import anthropic

token = Path(os.environ["SUBSURF_OAUTH_TOKEN_PATH"]).read_text().strip()
client = anthropic.AsyncAnthropic(auth_token=token)
```

### Attach A Codex App

Generate Codex attachment files:

```bash
subsurf-codex attach --app-dir /path/to/your/app
```

This writes:

```text
.env.subsurf.codex
subsurf_codex_cli_example.py
subsurf_codex_token_example.py
```

For apps that shell out to Codex, load the env file or set:

```bash
export CODEX_HOME=~/.config/subsurf/installs/<account-id>/codex_home
```

The app-side contract is:

```text
SubSurf owns isolated CODEX_HOME.
Codex login writes auth.json there.
Your app runs Codex with CODEX_HOME pointing there.
```

For trusted code that understands the stored credential type:

```bash
subsurf-codex token
subsurf-codex token --kind access-token
subsurf-codex token --kind api-key
subsurf-codex token --kind agent-identity
```

## LiteLLM

Register the SubSurf provider once during app startup:

```python
import litellm

from subsurf.litellm_provider import register_subsurf_provider

register_subsurf_provider()

response = litellm.completion(
    model="subsurf/claude-sonnet-4-6",
    messages=[{"role": "user", "content": "Say hello."}],
    max_tokens=128,
)
print(response.choices[0].message.content)
```

Smoke-test the LiteLLM integration without a real token or network call:

```bash
subsurf-litellm-smoke
```

## Local Gateway

Run the gateway:

```bash
subsurf-gateway --host 127.0.0.1 --port 8765
```

List models:

```bash
curl -s http://127.0.0.1:8765/v1/models
```

Call OpenAI-compatible chat completions:

```bash
curl -s http://127.0.0.1:8765/v1/chat/completions \
  -H 'content-type: application/json' \
  --data-binary @- <<'JSON'
{"model":"sonnet","messages":[{"role":"user","content":"Reply with exactly: ok"}],"max_tokens":32}
JSON
```

If you want to protect the local gateway with a token:

```bash
export SUBSURF_GATEWAY_ACCESS_TOKEN='choose-a-local-secret'
subsurf-gateway --host 127.0.0.1 --port 8765
```

Then call it with:

```bash
curl -s http://127.0.0.1:8765/v1/models \
  -H "authorization: Bearer $SUBSURF_GATEWAY_ACCESS_TOKEN"
```

## Models

Claude aliases:

```text
opus   -> current Opus fallback alias
sonnet -> current Sonnet fallback alias
haiku  -> current Haiku fallback alias
```

Codex/OpenAI aliases include:

```text
latest
flagship
pro
mini
nano
codex
spark
chat
```

The fallback catalogs are convenience aliases. When credentials are available,
SubSurf tries account-scoped discovery first:

```bash
subsurf-models --live
subsurf-codex models --live
```

## Testing

Run the full local suite:

```bash
python -m pytest
```

Run lint:

```bash
python -m ruff check .
```

Run the local smoke/adversarial QA pack:

```bash
python -m subsurf.qa
```

Run a safe no-login Codex wizard smoke test:

```bash
tmp=$(mktemp -d /tmp/subsurf-smoke.XXXXXX)
python -m subsurf.wizard \
  --provider codex \
  --account-id smoke-codex \
  --codex-home "$tmp/codex_home" \
  --attach-dir "$tmp/app" \
  --skip-login \
  --no-overwrite-attach
rm -rf "$tmp"
```

This verifies setup rendering, isolated `CODEX_HOME` creation, model fallback,
and app attachment without touching real auth.

## Troubleshooting

### `python -m subsurf.wizard` Cannot Find `subsurf`

You are probably not in the environment where SubSurf is installed. From the
repo:

```bash
cd /Users/jq/Documents/Advisor/PilotCC/SubSurf
python -m pip install -e '.[dev]'
python -m subsurf.wizard --status
```

### The Wizard Defaults Or Prompts Differently Than Expected

Use explicit provider flags:

```bash
python -m subsurf.wizard --provider claude
python -m subsurf.wizard --provider codex
```

Use the cleared-screen intro:

```bash
python -m subsurf.wizard
```

Use the classic prompt style:

```bash
python -m subsurf.wizard --no-clear-screen
```

### Claude Refresh Fails With `invalid_grant`

The saved refresh token is invalid. Re-run the Claude wizard, complete `/login`
in the isolated Claude Code session opened by SubSurf, then `/exit`.

### Curl Says The Request Body Is Invalid JSON

Use `--data-binary @-` with a heredoc exactly like this:

```bash
curl -s http://127.0.0.1:8765/v1/chat/completions \
  -H 'content-type: application/json' \
  --data-binary @- <<'JSON'
{"model":"sonnet","messages":[{"role":"user","content":"Reply with exactly: ok"}],"max_tokens":32}
JSON
```

The closing `JSON` must start at the beginning of the line.

### Codex Auth Is Missing

Run:

```bash
python -m subsurf.wizard --provider codex
```

or:

```bash
subsurf-codex login
```

Then check:

```bash
subsurf-codex status
subsurf-codex models --live
```

## Command Reference

```text
subsurf-wizard           Guided setup and status
subsurf-setup            Script-friendly setup flow
subsurf-attach           Attach Claude token files to an app
subsurf-codex            Codex isolated login/status/token/attach helpers
subsurf-gateway          Local OpenAI/Anthropic-compatible gateway
subsurf-models           Claude model aliases and live discovery
subsurf-openai-models    Codex/OpenAI model aliases
subsurf-litellm-smoke    LiteLLM provider smoke test
subsurf-qa               Local smoke/adversarial QA pack
subsurf-bridge           Claude token keepalive daemon
subsurf-pool             Token pool watcher utilities
```

## Project Layout

```text
subsurf/
  wizard.py              # guided CLI setup
  setup.py               # script-friendly setup flow
  anthropic_oauth.py     # Anthropic bearer-token client
  codex_auth.py          # isolated CODEX_HOME helpers
  model_discovery.py     # account-scoped model discovery and cache helpers
  models.py              # Claude model aliases
  openai_models.py       # Codex/OpenAI model aliases
  gateway.py             # local HTTP gateway
  litellm_provider.py    # LiteLLM custom provider
  qa.py                  # local smoke/adversarial QA runner
scripts/
  cc_session_bridge.py   # macOS Keychain refresh/publish daemon
  oauth_pool.py          # host token-pool utilities
docs/
  architecture.md
  codex-login-provider.md
  gateway.md
  qa.md
  wizard.md
```

## More Docs

- [Wizard guide](docs/wizard.md)
- [Codex login provider](docs/codex-login-provider.md)
- [Gateway API](docs/gateway.md)
- [Architecture](docs/architecture.md)
- [QA plan](docs/qa.md)
