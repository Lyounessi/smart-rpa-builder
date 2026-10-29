# Muse integration — Phase 1: API connection

Phases 2 and 3 are implemented: see [context snapshots and spending controls](muse-context-budget.md) and [Build with Muse clarification](muse-conversation.md). Run migrations before using the tracked connection check or review interface. Robot generation remains deferred.

The backend uses the OpenAI Python SDK against Meta Model API at the fixed URL `https://api.meta.ai/v1`. The initial model is `muse-spark-1.3`, configurable through `META_MODEL`. This calls Meta's model API directly; it does not launch the Muse Code terminal agent or grant it shell, filesystem, browser, or email tools.

## Local configuration

Install the updated pinned project environment during setup:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-inspector.lock.txt
```

Put your own API key in the ignored local `.env`:

```dotenv
MUSE_APIKEY=
META_MODEL=muse-spark-1.3
META_TIMEOUT_SECONDS=45
```

Fill in `MUSE_APIKEY` locally; never paste it into project instructions, generated code, screenshots, logs, or frontend JavaScript. The application passes that value explicitly to the SDK. Meta's examples use `MODEL_API_KEY`, but this project intentionally uses the user-requested `MUSE_APIKEY` name. There is no implicit `OPENAI_API_KEY` fallback. Process environment variables override `.env` through the existing python-dotenv setup.

The key is optional for normal project, inspector, catalog and runner features. Missing configuration produces a clear error only when the Meta connection is requested. The key has no browser form or public status endpoint in this milestone. Judges can install the dependencies, create their own local `.env` from `.env.example`, set their own key/model, and run the explicit check below. No credentials are embedded in source or images; any future container setup must inject them at runtime and exclude `.env` from its build context.

## Explicit connection check

```powershell
.\.venv\Scripts\python.exe manage.py check_muse_connection
```

This command makes **one paid request** to `/v1/responses`. It sends only `Reply exactly OK.`, with minimal reasoning, no tools, `store=False`, and `max_output_tokens=128`. The cap includes reasoning and visible output. It never reads or sends a project, dataset, capture, framework source, or robot. There is no live API request in automated tests or normal page rendering.

Successful output contains the configured model, measured elapsed time, and input/output/cached token counts if supplied. It does not print the key, prompt/response body, authorization headers, provider error body, or raw SDK exceptions. Missing token metadata is reported as unavailable rather than zero. A completed response with the expected `OK` confirmation is required for success. A truncated or unexpected response is reported without retrying.

SDK retries are explicitly zero. Redirects are disabled and the API URL cannot be supplied by a user. `META_TIMEOUT_SECONDS` must be between 1 and 120; the default is 45. HTTPX read timeout uses this value, connect/write are capped at 10 seconds, and pool wait is capped at 5. These are bounded I/O timeouts, not a guaranteed total wall-clock deadline for every possible network condition. Clients/transports are closed after success or failure.

## Errors

The backend maps errors to fixed, safe messages and the command exits nonzero:

| Code | Meaning |
|---|---|
| `missing_key` / `invalid_configuration` | Set the required local key or correct the model/timeout configuration |
| `authentication` | Meta rejected the key |
| `permission` | Account/model access denied |
| `billing` | Provider reports a credit or billing issue |
| `model_not_found` | Model/endpoint unavailable |
| `rate_limited` | Provider limit reached; no retry performed |
| `timeout` / `connection` | Request timed out or network unavailable; no retry performed |
| `invalid_request` | Provider rejected request parameters |
| `provider` / `client` | Provider or local SDK failure |
| `unexpected_response` | Response did not complete with the expected bounded confirmation |

A timed-out request may still have reached the provider and incurred charges. Re-running the command is another explicit request; do not place it in a retry loop. The command now passes through the persistent Phase 2 usage ledger and spending reservation gate. It remains a fixed diagnostic, not a generation endpoint or automated monitor.

## Backend boundary and tests

`muse_builder/client.py` owns configuration validation, SDK calls and safe errors. `muse_builder/service.py` wraps application calls with spending/usage controls. `muse_builder/management/commands/check_muse_connection.py` exposes only the fixed diagnostic. The Phase 2 ledger requires its database migration; it does not send project data during a connection check.

```powershell
.\.venv\Scripts\python.exe manage.py test muse_builder
```

Tests use the real SDK with mocked HTTP transport and a fictional key. They verify request shape/host, token cap, no SDK retries, timeout settings, disabled redirects, missing/invalid configuration, authentication/permission/billing/model/rate-limit/provider failures, network failures, redaction, incomplete responses, optional usage metadata, and safe command output. No automated test calls Meta or executes robots.

## Official references

Checked on 2026-10-29:

- [Meta quickstart](https://dev.meta.ai/docs/quickstart): SDK/base URL/model and explicit API key configuration.
- [Responses API](https://dev.meta.ai/docs/protocols/responses): response format, stateless requests, minimal reasoning and output-token limits.
- [Error handling](https://dev.meta.ai/docs/error-handling): provider status codes and SDK error categories.

Filtered multimodal context, a versioned framework contract and usage/spending controls are implemented in Phase 2. Phase 3 adds bounded clarification sessions and explicit specification confirmation. Draft generation/static validation and a separate reviewed-version test path remain next.
