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

Optional local API key:

```bash
export SUBSURF_GATEWAY_API_KEY='local-secret'
subsurf-gateway
```

Then send either:

```text
Authorization: Bearer local-secret
X-Api-Key: local-secret
```

## Models

The gateway exposes Claude Code-style family aliases:

```text
opus   -> claude-opus-4-8
sonnet -> claude-sonnet-4-6
haiku  -> claude-haiku-4-5-20251001
```

It also lists known full Haiku, Sonnet, and Opus model IDs through
`/v1/models`. Unknown full model IDs pass through to Anthropic so newly
available Claude models do not require a SubSurf release before you can try
them.

List the local catalog:

```bash
subsurf-models
subsurf-models --json
```

## Unsupported Today

The gateway intentionally fails fast for:

```text
streaming, tools, tool_choice, functions, response_format, stop
```

Those should be added deliberately with tests rather than silently ignored.

