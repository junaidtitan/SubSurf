# Codex Login Provider

This note captures the research and implementation plan for using Codex login
as a SubSurf provider, parallel to the Claude Code login path.

## Source Findings

The Codex source and manual show these constraints:

- Codex local state is rooted at `CODEX_HOME`. Default user state is `~/.codex`.
- Codex CLI credential storage is controlled by `cli_auth_credentials_store`.
- `cli_auth_credentials_store = "file"` stores credentials in
  `$CODEX_HOME/auth.json`.
- `auth.json` can hold one of several credential shapes:
  - API-key auth: `auth_mode = "apikey"` plus `OPENAI_API_KEY`.
  - ChatGPT OAuth auth: `auth_mode = "chatgpt"` plus `tokens`.
  - Agent identity auth: `auth_mode = "agentIdentity"` plus `agent_identity`.
- `codex login` supports browser login by default.
- `codex login --device-auth` supports device-code login.
- `codex login --with-api-key` reads an API key from stdin.
- `codex login --with-access-token` reads a Codex access token from stdin.

The important safety conclusion is that SubSurf should not read or mutate
normal `~/.codex` state by default. This mirrors the Claude isolation rule for
`CLAUDE_CONFIG_DIR`.

## Implemented Plan

SubSurf now treats Codex as a separate provider:

```text
Claude provider:
  isolated CLAUDE_CONFIG_DIR
  macOS Keychain service derived from that config dir
  token file consumed by Anthropic clients

Codex provider:
  isolated CODEX_HOME
  file-backed auth.json
  environment and token helper consumed by Codex/OpenAI-aware apps
```

The generated Codex home is:

```text
~/.config/subsurf/installs/<account-id>/codex_home/
```

SubSurf writes:

```toml
cli_auth_credentials_store = "file"
```

to:

```text
~/.config/subsurf/installs/<account-id>/codex_home/config.toml
```

The user-facing commands are:

```bash
subsurf-setup --provider codex
subsurf-codex prepare
subsurf-codex login
subsurf-codex login --device-auth
subsurf-codex models --aliases
subsurf-codex status
subsurf-codex env
subsurf-codex token
subsurf-codex attach --app-dir /path/to/app
```

Default model selection is:

```text
gpt-5.5
```

Select another model with:

```bash
subsurf-setup --provider codex --codex-model gpt-5.4-mini
subsurf-codex prepare --model gpt-5.5-pro
```

Model availability is account-scoped. After login, SubSurf can query the
isolated account with:

```bash
subsurf-codex models --live
```

API-key auth uses OpenAI's `/v1/models` route. ChatGPT/Codex auth uses Codex's
ChatGPT backend model route. Results are cached under the per-install state dir
and the offline catalog remains only a fallback and alias layer. Explicit model
ids pass through so a newly available model can still be used before this
catalog is refreshed.

`subsurf-codex token` is explicit because the credential type matters. A
ChatGPT/Codex access token is not relabeled as an OpenAI Platform API key.

## App Attachment Contract

For apps that run Codex:

```text
CODEX_HOME=<SubSurf isolated codex_home>
codex ...
```

For trusted apps that know how to use the specific stored credential type:

```text
subsurf-codex token --kind access-token
subsurf-codex token --kind api-key
subsurf-codex token --kind agent-identity
```

The default `--kind any` prefers ChatGPT access token, then agent identity, then
API key.

## Deferred Work

The current implementation intentionally does not add a local OpenAI/Codex API
proxy. That should be a separate feature because the target surface matters:

- If the app shells out to Codex, the isolated `CODEX_HOME` is enough.
- If the app calls OpenAI Platform APIs, API-key auth is the clean path.
- If the app calls ChatGPT/Codex backend APIs, it must use the Codex credential
  with that backend's expected protocol.

Any proxy should preserve those distinctions instead of pretending all
credentials are interchangeable.
