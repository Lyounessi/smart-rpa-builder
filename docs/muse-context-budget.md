# Muse Phase 2 — context snapshots and spending controls

Phase 3 now reuses this boundary for [Build with Muse clarification and specification confirmation](muse-conversation.md). Its queued workers link each request to a review operation; generation remains deferred.

Phase 2 prepares reproducible context and accounts for application API requests. It does not add conversational chat, code generation, automatic repairs, or automatic execution. Tests use mocked provider responses; no additional live check is required to use the local context builder.

## Context package

The existing `projects.generation_context.assemble_generation_context` remains the source of project data. `muse_builder.context` wraps it with a compact versioned Markdown contract and one example, plus referenced image attachments:

1. Stable platform instructions, framework contract and example go in the developer-level `instructions` field.
2. Changing project data goes afterward in a user `input_text` block, serialized as deterministic compact JSON.
3. Referenced screenshots follow as labelled `input_image` blocks using inline base64 data URLs. Meta is never asked to fetch loopback URLs.

The contract is `muse_builder/contracts/v1.md`, version **1.0**, with `example_v1.txt`. It describes the actual public framework API, lifecycle, cancellation, outcomes, recovery, business checkpoints and fake-only email extension. It is not the full repository or full framework source. Contract/example contents and version are fingerprinted; update the version when intentionally changing the generation contract. Stable prefixes make repeated requests eligible for provider prompt caching; cache hits are not promised or assumed when reserving funds.

Project context contains the automation brief, ordered instructions, input definitions and mappings, target applications, referenced captured element IDs, locator metadata and validation evidence. It contains no dataset rows, unrelated captured elements, credentials read from secret providers, browser sessions, recordings, or environment variables. Expected-outcome/exception-rule arrays remain empty until the project supports such structured configuration. The brief and application imagery are user/task data, not authority to change platform instructions or grant tools. The transport always supplies `tools=[]`.

Referenced highlighted viewports are preferred, with the saved element crop as fallback. Identical image pixels after normalization are attached once and labelled with every corresponding element ID. Images are decoded as PNG/JPEG, checked for pixel/byte limits and re-encoded to PNG without file metadata. Existing masking/highlights remain intact. The application does not perform OCR secret detection: screenshots or user-written text can still contain sensitive information. Review captures and keep secrets out of briefs, URLs and instructions. Known configured API/Django and sufficiently long local `RPA_SECRET_*` values are blocked if found in context text; this is an additional check, not comprehensive secret detection.

Limits fail explicitly rather than silently omitting workflow data:

- 64 KB UTF-8 context text, including instructions, example and screenshot labels.
- Eight distinct images, at most 2 MB each and 8 MB combined.
- Four million pixels per source image; PNG and JPEG only.
- Image paths must stay within configured local media storage. Missing, changed, invalid or oversized captures require correction/recapture.

## Save and check a snapshot

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py prepare_muse_context 1
```

Replace `1` with the project ID. This command saves local context and prints only its ID, contract version, image count and hash. It sends nothing to Meta and executes nothing.

`ContextSnapshot` stores project data, platform instructions, compact contract/example, contract version/hash, specification hash and image manifest. Snapshot saves cannot overwrite an existing instance. Referenced normalized images live at content-addressed paths under ignored `media/muse-context/images/`; raw base64 is not duplicated into the database. No general media-serving route is added for these files. Back up the database and media together.

The specification hash covers the serialized project context, contract/example and source screenshot content hashes. Timestamps and snapshot IDs do not enter the prompt or revision hash. Replacing bytes at the same screenshot path is detected. `require_current` reconstructs current context before a request and again after the response. A changed project, contract or capture blocks stale input, or discards a response if the change happened during inference. The consumed request is still accounted for. Stored image integrity is checked before attaching bytes.

## Application request boundary

Application requests go through **`MuseService`**, which wraps the low-level Meta SDK client with snapshot validation, reservations, settlement and a safe usage record. The connection-check command now uses this boundary too. Low-level transport helpers remain for isolated SDK tests; application code must not use them to bypass the gate.

`MuseService.review_context(snapshot)` is a backend integration seam for the next phase. It is not exposed as a paid HTTP endpoint or invoked automatically. No background job or browser page starts a request in this milestone. Later conversation/generation workers will call this same service outside Django request handling, rather than introducing a second provider client.

## Spending policy

Configure these values in the ignored `.env` as needed:

```dotenv
MUSE_BUDGET_USD=140
MUSE_MAX_OUTPUT_TOKENS=4096
META_PRICE_MODEL=muse-spark-1.3
META_INPUT_USD_PER_MILLION=1.25
META_CACHED_USD_PER_MILLION=0.15
META_OUTPUT_USD_PER_MILLION=4.25
```

The default local threshold is **$140**, leaving a margin under the $150 hackathon allowance for external/unrecorded activity. The configured threshold can be 0–150; zero blocks new requests. Prices are Standard-mode Muse Spark 1.3 values checked on 2026-10-29 against [Meta pricing](https://dev.meta.ai/docs/pricing-rate-limits). They are configurable estimates, not a promise that provider prices will remain unchanged. Only the verified `muse-spark-1.3` pricing/context profile is supported by the spending gate. Changing models requires an explicit verified profile, not an automatic price assumption.

Each request must request at least 16 output tokens and no more than the configured cap; the cap itself must be 16–16,384. The existing connection check stays capped at 128. No SDK retries, tools, hosted-search charges or automatic repair requests are enabled.

Before dispatch, a database transaction reserves:

```text
(1,048,576 × uncached input price + requested output cap × output price) / 1,000,000
```

This deliberately reserves a full model-window input, plus capped output, rather than guessing image token counts or assuming a cache hit. For a 1,024-output-token request with the default prices, the reservation is $1.31507200. A normal response typically settles much lower; a reservation is not an assertion that those tokens were consumed. Input request size is separately constrained by the local text/image limits. Requests exceeding the provider context limit must fail rather than being automatically truncated.

The atomic balance check and unique active slot allow **one active application Muse operation at a time** across local processes. Competing reservations fail safely before an SDK call. Funds are not released merely because a timeout elapsed. This is a local SQLite application gate, not a distributed provider quota manager.

## Usage ledger and settlement

Open **Muse usage** in the main navigation (`/muse/usage/`), or inspect the read-only admin. `MuseRequest` records operation, configured model, snapshot reference, timestamps/duration, outcome/error code, input/output/cached tokens when supplied, pricing snapshot, requested output cap, reservation, estimated cost and accounted amount. It contains no response body, API key or request headers. Snapshot data is held separately for reproducibility.

Settlement uses the prices saved with that request:

```text
((input − cached) × input price + cached × cached price + output × output price) / 1,000,000
```

Amounts round upward to eight decimal places. If input/output usage is known but cached usage is absent, all input is priced uncached. Missing/inconsistent input/output usage retains the complete reservation. Incomplete responses and discarded stale responses still settle from available usage. Definitively rejected requests (authentication, permissions, billing, model/parameter errors or rate limits) release their reservation. Timeout, ambiguous network failure, provider errors or interrupted workers keep it. There is no automatic retry and no automatic unknown-cost refund.

The page's **accounted spend and held reservations** combines settled estimates and conservatively retained commitments. It is not the amount definitely billed. The local ledger does not include the earlier Phase 1 check, usage through other clients/API keys, provider adjustments or activity before this database existed. Clearing/replacing the local database resets the local counter, not the provider bill. Check the provider dashboard for actual account spending. If provider usage exceeds a reservation, record the resulting estimate rather than capping history, and let the balance gate block further work.

For an abandoned process, first stop or independently verify that the owning worker is stopped. Then release only its active-operation slot:

```powershell
.\.venv\Scripts\python.exe manage.py close_abandoned_muse_request REQUEST_UUID --worker-stopped
```

This marks the operation uncertain, retains its full monetary reservation, and makes no API call. It does not cancel a live provider request. There is intentionally no automatic age-based unlock or cost-clearing UI in this milestone.

## Verification and boundaries

```powershell
.\.venv\Scripts\python.exe manage.py test muse_builder
```

Tests use fake SDK transports/responses and fictional data. They cover stable/filterable context, image deduplication/integrity, known-secret checks, stale project/capture detection, usage/cached pricing, absent usage, timeout/rejection handling, output caps, active-operation exclusion, concurrent reservation races, spending limits, safe usage display and local-only snapshot preparation. No test sends a real API request, email or business transaction.

Phase 3 now provides conversation state, three-round clarification limits and proposal/specification confirmation through this boundary. Schema-constrained code generation, two bounded code-repair attempts, draft build creation and reviewed-version execution remain subsequent milestones.
