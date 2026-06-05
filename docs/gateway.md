# Local Gateway

SubSurf includes a small local gateway for apps that want HTTP instead of a
Python import.

Install with gateway dependencies:

```bash
python -m pip install -e '.[gateway]'
```

Run:

```bash
subsurf-gateway --host 127.0.0.1 --port 8765
```

Endpoints:

```text
GET  /health
GET  /subsurf/status
GET  /v1/models
POST /v1/chat/completions
POST /v1/messages
```

OpenAI-compatible call:

```bash
curl -s http://127.0.0.1:8765/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{
    "model": "sonnet",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 128
  }'
```

Anthropic Messages-compatible call:

```bash
curl -s http://127.0.0.1:8765/v1/messages \
  -H 'content-type: application/json' \
  -d '{
    "model": "haiku",
    "system": "Be concise.",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 128
  }'
```

Optional local gateway access token:

```bash
export SUBSURF_GATEWAY_ACCESS_TOKEN='local-secret'
subsurf-gateway
```

Then send either:

```text
Authorization: Bearer local-secret
X-SubSurf-Token: local-secret
```

This token only protects the local SubSurf gateway. It is not an Anthropic API
key; upstream Anthropic calls still use the Claude Code OAuth token file.

## Models

The gateway exposes Claude Code-style family aliases:

```text
opus   -> claude-opus-4-8
sonnet -> claude-sonnet-4-6
haiku  -> claude-haiku-4-5-20251001
```

`/v1/models` tries account-scoped Claude model discovery with the configured
SubSurf OAuth token and falls back to the offline alias catalog if discovery is
unavailable. Unknown full model IDs pass through to Anthropic so newly available
Claude models do not require a SubSurf release before you can try them.

List the local catalog:

```bash
subsurf-models
subsurf-models --json
subsurf-models --live
```

## Unsupported Today

The gateway intentionally fails fast for:

```text
streaming, tools, tool_choice, functions, response_format, stop
```

Those should be added deliberately with tests rather than silently ignored.
