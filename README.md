# SubSurf

SubSurf is a standalone extraction of the Claude Code OAuth piggyback path:

- Read Claude Code OAuth sessions from macOS Keychain.
- Keep access tokens fresh with refresh-token rotation.
- Publish token files for local processes or VM fleets.
- Call Anthropic with `Authorization: Bearer <OAuth token>`.
- Register as a LiteLLM custom provider named `subsurf`.
- Serve a small local OpenAI/Anthropic-compatible gateway.
- Present requests with Claude Code identity headers/system block.
- Signal throttles through files so a host-side pool watcher can rotate tokens.

It is intentionally small and separate from Pilot.

## Layout

```text
subsurf/
  anthropic_oauth.py      # bearer-token Anthropic client + Claude Code spoof
  litellm_provider.py     # LiteLLM custom provider for model="subsurf/..."
  litellm_smoke.py        # manual LiteLLM smoke test CLI
  gateway.py              # small local HTTP gateway
  models.py               # Claude model catalog and aliases
  setup_tui.py            # Textual one-button setup UI
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
  gateway.md              # local gateway API
  qa.md                   # unit, smoke, and adversarial QA plan
  wizard.md               # guided setup and app attachment
```

## Quick Start

Install in editable mode:

```bash
cd SubSurf
python -m pip install -e '.[dev]'
```

Dead-simple setup UI:

```bash
python -m subsurf.setup_tui
```

If SubSurf is installed in editable mode, this is the same as:

```bash
subsurf-setup
```

Click `Start Setup`. When Claude Code opens in the terminal, run `/login`,
finish browser auth, then run `/exit`. The UI enrolls the token, starts
keepalive, writes `./sample-app`, and runs live Python and gateway piggyback
checks.

Terminal-only setup:

```bash
python -m subsurf.wizard
```

SubSurf automatically creates a stable local account id like
`subsurf-4f1a2b3c`, stores it in `~/.config/subsurf/install_id`, and uses an
isolated Claude config directory such as `~/.claude-subsurf-subsurf-4f1a2b3c`.
Avoid `~/.claude` unless you intentionally pass
`--allow-shared-claude-config`.

After setup, rerun the live test any time:

```bash
python -m subsurf.demo
```

or:

```bash
subsurf-demo
```

The setup flow walks through:

1. Logging into Claude Code in an isolated `CLAUDE_CONFIG_DIR`.
2. Enrolling that Keychain session into `~/.config/subsurf/cc_accounts.json`.
3. Publishing `~/.config/subsurf/oauth_token_<account-id>`.
4. Starting the keepalive daemon.
5. Creating attachment files for another app.

Publish the current Claude Code session token once:

```bash
python scripts/cc_session_bridge.py --once
```

Keep tokens fresh:

```bash
python scripts/cc_session_bridge.py --interval 60
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

Default token and IPC files live under `~/.config/subsurf/`.

## Attaching Another App

The app does not own refresh. SubSurf owns refresh and keeps a token file current.
Your app should either:

- use `SubSurfEngine`, which reads `SUBSURF_OAUTH_TOKEN_PATH`, or
- read the token file itself and construct an Anthropic SDK client with
  `auth_token=token`.

Generate app-side files:

```bash
subsurf-attach --app-dir /path/to/your/app --account-id "$(cat ~/.config/subsurf/install_id)"
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
