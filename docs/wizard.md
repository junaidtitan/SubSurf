# Wizard Guide

Preferred setup UI:

```bash
subsurf-setup
```

or:

```bash
python -m subsurf.setup_tui
```

Terminal-only setup:

```bash
subsurf-wizard
```

The setup moves through the flow in order and avoids naming collisions by
generating a stable account id like `subsurf-4f1a2b3c`. That id is stored in:

```text
~/.config/subsurf/install_id
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

## 2. Enrollment

The wizard reads the Keychain item for that config dir and stores the session
metadata in:

```text
~/.config/subsurf/cc_accounts.json
```

It then publishes:

```text
~/.config/subsurf/oauth_token_subsurf-4f1a2b3c
~/.config/subsurf/oauth_token
```

## 3. Keepalive

The wizard can start a background bridge process:

```bash
subsurf-bridge --interval 60
```

It records:

```text
~/.config/subsurf/subsurf_bridge.pid
~/.config/subsurf/subsurf_bridge.log
```

Check status:

```bash
subsurf-wizard --status
```

## 4. Attach Another App

Run:

```bash
subsurf-attach --app-dir /path/to/app --account-id "$(cat ~/.config/subsurf/install_id)"
```

The setup UI and default wizard already write `./sample-app`. Use
`subsurf-attach` when you want to attach a different app. It writes
`.env.subsurf` and Python examples.

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
