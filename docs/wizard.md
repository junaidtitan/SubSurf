# Wizard Guide

Preferred setup:

```bash
subsurf-setup
```

or:

```bash
python -m subsurf.setup
```

Terminal-only setup:

```bash
subsurf-wizard
```

Codex-provider setup:

```bash
subsurf-setup --provider codex
```

The direct wizard accepts the same provider choice:

```bash
subsurf-wizard --provider claude
subsurf-wizard --provider codex
```

The setup moves through the flow in order and avoids naming collisions by
generating a stable account id like `subsurf-4f1a2b3c`. That id is stored in:

```text
~/.config/subsurf/install_id
```

Per-install state is stored separately under:

```text
~/.config/subsurf/installs/subsurf-4f1a2b3c/
```

## 1. Claude Login

By default, the wizard uses:

- account id from `~/.config/subsurf/install_id`
- label equal to that account id
- isolated Claude config dir, for example `~/.claude-subsurf-subsurf-4f1a2b3c`

Use `subsurf-wizard --manual` only if you want to answer those prompts yourself.

Do not use `~/.claude` for SubSurf setup. SubSurf intentionally uses an
isolated Claude config directory so Claude Code creates a separate Keychain
OAuth entry and does not collide with your normal Claude Code session.

It can launch:

```bash
CLAUDE_CONFIG_DIR=~/.claude-subsurf-subsurf-4f1a2b3c claude
```

Inside Claude Code, complete `/login`, finish browser auth, then run `/exit`.
When the Claude process exits, the wizard continues.

If you explicitly pass `--config-dir ~/.claude`, the wizard refuses by default.
Only use `--allow-shared-claude-config` when you intentionally want to share the
normal Claude Code session.

Do not run `/login` in your normal Claude Code terminal for SubSurf setup. Let
the wizard launch Claude with the isolated `CLAUDE_CONFIG_DIR` shown above.

## 2. Enrollment

The wizard reads the Keychain item for that config dir and stores the session
metadata in:

```text
~/.config/subsurf/installs/subsurf-4f1a2b3c/cc_accounts.json
```

It then publishes:

```text
~/.config/subsurf/installs/subsurf-4f1a2b3c/oauth_token_subsurf-4f1a2b3c
~/.config/subsurf/installs/subsurf-4f1a2b3c/oauth_token
```

## 3. Keepalive

The wizard can start a background bridge process using the per-install account
file. The exact command is printed during setup and includes `--accounts-file`,
`--token-file`, and `--pool-file`.

It records:

```text
~/.config/subsurf/installs/subsurf-4f1a2b3c/subsurf_bridge.pid
~/.config/subsurf/installs/subsurf-4f1a2b3c/subsurf_bridge.log
```

Check status:

```bash
subsurf-wizard --status
```

## 4. Attach Another App

Run:

```bash
subsurf-attach --app-dir /path/to/app
```

The setup command and default wizard already write `./sample-app`. Use
`subsurf-attach` when you want to attach a different app. It writes `.env.subsurf`
and Python examples.

The app-side contract is:

```text
SubSurf keepalive refreshes the token file.
Your app reads SUBSURF_OAUTH_TOKEN_PATH.
Your app sends Anthropic Bearer auth with that token.
```

If the app is Python, the simplest integration is:

```python
from subsurf import SubSurfEngine

text = await SubSurfEngine().complete([
    {"role": "user", "content": "hello"},
])
```

If the app already has an Anthropic wrapper, attach directly:

```python
from pathlib import Path
import os

import anthropic

token = Path(os.environ["SUBSURF_OAUTH_TOKEN_PATH"]).read_text().strip()
client = anthropic.AsyncAnthropic(auth_token=token)
```

If the app already uses LiteLLM, register the SubSurf provider once:

```python
import litellm

from subsurf.litellm_provider import register_subsurf_provider

register_subsurf_provider()
response = litellm.completion(
    model="subsurf/claude-sonnet-4-6",
    messages=[{"role": "user", "content": "hello"}],
)
```

For OAuth piggyback robustness, preserve the Claude Code identity headers and
first system block shown in `subsurf_direct_anthropic_example.py`.

## Codex Login Provider

The Codex path is separate from the Claude path. It is for apps that should use
Codex/OpenAI-backed auth, not Claude/Anthropic auth.

Run:

```bash
subsurf-setup --provider codex
```

By default, SubSurf creates a per-install Codex home:

```text
~/.config/subsurf/installs/subsurf-4f1a2b3c/codex_home/
```

and writes:

```toml
cli_auth_credentials_store = "file"
```

to that home's `config.toml`. This is the guard that prevents the setup from
using your normal `~/.codex` or keyring-backed Codex session.

Useful lower-level commands:

```bash
subsurf-codex prepare
subsurf-codex login
subsurf-codex login --device-auth
subsurf-codex models --aliases
subsurf-codex status
subsurf-codex env
subsurf-codex token
subsurf-codex attach --app-dir /path/to/app
```

Default model selection starts at `gpt-5.5`, then setup tries to discover the
models available to the isolated account. If you did not request a model
explicitly, SubSurf rewrites the isolated Codex config to a discovered
account-available model when needed. Pick a model during setup:

```bash
subsurf-setup --provider codex --codex-model gpt-5.4-mini
subsurf-setup --provider codex --codex-model codex
subsurf-wizard --provider codex --codex-model gpt-5.5-pro
```

After login, run `subsurf-codex models --live` to query models available to that
isolated account. Known offline aliases are listed by
`subsurf-codex models --aliases`. Explicit model IDs pass through, so a newly
available model can be used even before SubSurf's fallback alias catalog is
updated.

If an app needs to run Codex, set:

```bash
export CODEX_HOME=~/.config/subsurf/installs/<account-id>/codex_home
```

or load the generated `.env.subsurf.codex` file.

Safety rule:

```text
Do not use ~/.codex for SubSurf Codex setup unless you intentionally pass
--allow-shared-codex-home.
```
