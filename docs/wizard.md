# Wizard Guide

Run:

```bash
subsurf-wizard
```

The wizard moves through the setup in order.

## 1. Claude Login

The wizard asks for:

- an account id, for example `subsurf1`
- a label, usually an email
- an isolated Claude config dir, for example `~/.claude-subsurf-subsurf1`

Do not use `~/.claude` for SubSurf setup. SubSurf intentionally uses an
isolated Claude config directory so Claude Code creates a separate Keychain
OAuth entry and does not collide with your normal Claude Code session.

It can launch:

```bash
CLAUDE_CONFIG_DIR=~/.claude-subsurf-subsurf1 claude
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
~/.config/subsurf/oauth_token_subsurf1
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
subsurf-attach --app-dir /path/to/app --account-id subsurf1
```

This writes `.env.subsurf` and two Python examples.

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
