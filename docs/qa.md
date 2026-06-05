# QA And Manual Testing

SubSurf has three local QA layers today.

## 1. Unit Tests

Run:

```bash
python -m pytest
```

This covers token loading, message conversion, throttle handling, attach-file
generation, wizard helpers, pool helpers, and the LiteLLM custom provider.

## 2. Local QA Runner

Run setup once:

```bash
python -m subsurf.setup_tui
```

Click `Start Setup`. When Claude Code opens, run `/login`, finish browser auth,
then run `/exit`.

Run the foolproof live demo:

```bash
python -m subsurf.demo
```

or, after editable install:

```bash
subsurf-demo
```

It avoids shell JSON quoting by making both the Python and gateway calls from
inside Python.

Run the local smoke and adversarial pack:

```bash
subsurf-qa
```

Smoke cases only:

```bash
subsurf-qa --only smoke
```

Adversarial cases only:

```bash
subsurf-qa --only adversarial
```

Today this checks provider registration, sync/async LiteLLM calls, gateway
OpenAI/model endpoints, missing and empty token files, unsupported
tools/streaming, gateway auth, and malformed message roles.

## 3. LiteLLM Smoke Test

Offline mock mode checks provider registration and response shape without a
token file or network call:

```bash
subsurf-litellm-smoke
```

Async mock mode:

```bash
subsurf-litellm-smoke --async-call
```

Live mode checks the real token file and Anthropic call path:

```bash
subsurf-litellm-smoke --live --prompt "Say hello through LiteLLM."
```

If live mode reports a missing token file, run:

```bash
subsurf-setup
```

or:

```bash
subsurf-wizard
```

## 4. App Attachment Test

Generate examples into a scratch app:

```bash
subsurf-attach --app-dir /tmp/subsurf-app --account-id "$(cat ~/.config/subsurf/install_id)"
```

Then inspect or run:

```bash
python /tmp/subsurf-app/subsurf_litellm_example.py
```

after loading `/tmp/subsurf-app/.env.subsurf` in that shell.

## Adversarial Fleet Direction

The gateway phase should add adversarial checks that run against the local
OpenAI-compatible endpoint and the LiteLLM provider:

- missing, empty, expired, and rotated token files
- concurrent requests during token rotation
- 429/rate-limit backoff and pool reassignment
- unsupported parameters such as streaming/tools until those are implemented
- malformed message roles, null content, and oversized payloads
- authenticated and unauthenticated gateway requests
- model aliases and newly released full model IDs
- fallback-request and fallback-grant abuse cases
- cross-app isolation for multiple account ids

The local smoke command remains the manual, developer-facing path for quick
checks between larger fleet runs.
