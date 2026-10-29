# Phase 3 — Build with Muse

Open a project and select **Build with Muse**, at `/projects/<project_id>/build/`. The page clarifies the saved workflow, presents proposed changes for review, and records an explicitly agreed specification. Clarification does not itself generate or execute code. After explicit confirmation, Phase 4 provides a separate paid draft-generation action; see [Muse draft generation](muse-generation.md).

## Configuration and use

Use the existing [Meta connection configuration](muse-integration.md) and [Phase 2 spending controls](muse-context-budget.md), install the pinned environment, and apply migrations. Pydantic 2 is now an explicit application dependency; it was already pinned through the SDK dependency set.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-inspector.lock.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

The API key remains in local `MUSE_APIKEY`. Missing credentials, a pricing/configuration problem or an exhausted spending threshold is displayed without exposing secrets. Normal GET requests, polling, local specification editing and final confirmation make no paid request.

1. Review the project's saved brief, steps, mappings and captures. Keep actual credentials out of text and screenshots.
2. Click **Review workflow with Muse (paid API request)**. This explicitly sends the filtered saved context and referenced screenshots through the budgeted service.
3. Answer targeted questions in their fields and add workflow context if needed. Submit **Send answers for review** only when another paid review is wanted.
4. Inspect assumptions and proposed changes. **Confirm this specification update** applies the validated bundle. **Reject update** leaves the project/specification unchanged. Pending changes must be reviewed before another API operation.
5. Complete the structured decisions and inspect the specification summary. Click **Confirm agreed specification** when it matches the intended workflow.

The agreed specification stores the fixed project context, decisions, explicitly resolved clarifications, confirmed assumptions, source specification hash and framework contract version/hash. Editing decisions or requesting another review clears the prior confirmation. Generation must consume a newly confirmed specification, not an unreviewed chat transcript.

## Bounded conversation

- At most **three paid review attempts per session**, including the initial saved-context review. Failed/queued attempts consume a round; no automatic retry is made.
- At most **three questions** and eight proposed changes in a provider response, with concise summaries/assumptions. Pydantic validates these limits in the backend.
- Each clarification request requests **1,536 output tokens**, including reasoning, within the existing global output cap. Configure the global cap at least this high to use clarification. There is no automatic cap increase or provider retry.
- The task is workflow clarification, not general chat. Platform instructions ask Muse to give concise questions, use information already supplied, state assumptions, and flag unsupported requests.
- The first review attaches saved screenshots. Follow-ups omit image attachments by default; the user can explicitly select **Include saved screenshots again** when needed.
- Later requests carry confirmed structured decisions, every outstanding question/recorded answer, missing local requirements, confirmed assumptions, and the last four exchanges. Original messages are retained in the database; unresolved questions do not disappear merely because their original message falls outside that recent window.
- The existing 64 KB text and image limits still apply. Oversized conversation context fails explicitly instead of silently dropping unresolved state.

When three attempts are used, further API calls are blocked. The user can edit the structured specification locally and explicitly acknowledge that outstanding questions are resolved by those decisions. Local editing cannot silently clear an unsupported-capability warning: correct the project/start a fresh review, or explicitly discuss and confirm removal of the unsupported request. Starting a fresh session is a deliberate action with a new source snapshot and its own bounded attempts; the global spending gate still applies. Prior sessions remain accessible through review history.

## Structured decisions and permitted changes

Session decisions describe robot behavior without adding lifecycle categories to the workflow-step model:

- Setup step IDs and per-row step IDs: every saved workflow step must appear exactly once, in workflow order.
- Stop/continue policies for known business rejection and technical errors.
- Explicit success criteria and known rejection handling.
- Recovery plan when either policy permits continuation; the framework still requires real recovery before continuing at execution time.

Initial policy values reflect framework defaults and await user confirmation. They do not claim that the user configured exception rules already. Explicit step targets, mappings and execution settings cannot be overridden by free-form chat.

Muse may propose session decisions, automation brief changes, step instruction edits, an existing input mapping for a Fill/Select step, or a referenced captured target from the same application. A proposal cannot add steps/actions, change application URLs, invent input fields or target IDs, configure secrets, change the budget/model, install dependencies or add capabilities. Existing ModelForms and project/application boundaries validate confirmed project edits. Batch updates are transactional and create a fresh context snapshot when project fields change. Rejected or manually superseded proposals cannot be reapplied.

Readiness requires valid local decisions, captured targets for the current UI actions, no outstanding questions or pending proposals, and no unsupported-request warning. Model readiness alone cannot bypass these checks. Local editing is a human specification review, not an automatic proof of semantic correctness. Neither model review nor these checks guarantee detection of every contradiction.

## Background architecture and traceability

`BuildSession` holds the snapshot, decisions, review count, state and confirmed specification. `BuildMessage` stores user messages and assistant summaries, structured results and original validated JSON for traceability. `BuildQuestion` retains answers and explicit resolution state. `BuildProposal` records confirmation/rejection. `BuildOperation` is one queued/running worker operation with a heartbeat and a unique local active slot.

The POST handler persists the operation and launches a fixed Django management command as a separate hidden process on Windows. It passes only an operation UUID, never message text or credentials, on the command line. The worker claims a queued operation atomically, calls the existing `MuseService`, validates the response and persists results. HTTP requests never wait for model inference. HTMX polls persisted state every two seconds while a review is active, and input forms are not editable during that operation. No Celery, Redis, WebSocket or streaming layer is introduced.

Each provider call links its `MuseRequest` usage/cost record to the corresponding operation. The existing one-active-request spending reservation still applies. Malformed/over-limit structured output is reported without automatic repair, and any consumed usage stays accounted for. Provider errors and worker failures appear as safe messages, without raw exceptions or keys. Schema-constrained output uses the Responses API's **`text.format`**, with an object JSON schema and `strict=True`. Every object forbids additional properties and requires its properties. The transmitted schema uses the documented structural subset; Pydantic independently enforces length/count/pattern and semantic constraints in the backend.

Source snapshots are checked before/during provider use and before confirmations. A project, capture or contract edit makes the existing session stale. Start a fresh review instead of silently generating from it. Forms also carry a session revision token so a stale tab cannot confirm unseen questions/changes. Final generation remains blocked until explicit agreed-specification confirmation.

Model text is rendered as escaped plain text, including question choices used in form help text. It is never interpreted as HTML, JavaScript, Python or a server template. No model response is executed, imported, or treated as permission to call tools. The interface retains the application's existing local single-user/loopback access model; project-scoped routes and CSRF protect its mutations.

## Interrupted worker recovery

A heartbeat older than five minutes is shown as a potential worker issue, without automatically retrying or releasing reservations. First stop/verify the owning worker. Then:

```powershell
.\.venv\Scripts\python.exe manage.py close_abandoned_build_review OPERATION_UUID --worker-stopped
```

The command closes the operation and, if necessary, its linked active request. Uncertain monetary reservations remain committed. It does not cancel provider work or issue another request. The operation ID is shown on the active review page and in the read-only admin. Do not use recovery while its worker may still be running.

## Verification

```powershell
.\.venv\Scripts\python.exe manage.py test muse_builder.test_conversation muse_builder.tests
```

Tests mock the provider and process launch. They cover free GET/queued workers, structured response limits/schema transport, explicit confirmation, supported/foreign changes, rejected proposal replay prevention, three rounds, local edits, preservation of unresolved decisions, unsupported requests, stale context/forms, CSRF/project scoping, missing credentials, duplicate submissions, usage linkage, safe rendering, confirmation invalidation and abandoned-worker recovery. No automated test calls Meta, sends an email or executes business transactions. Any live check must be explicit and use reviewed context.

Official reference: [Meta structured output and strict schema rules](https://dev.meta.ai/docs/structured-output), verified 2026-10-29. API calls, budget handling and context construction reuse the prior phases. Draft generation, up to two bounded code repairs, static compatibility validation and versioned draft storage are now available in Phase 4. [Explicit reviewed testing](draft-testing.md) is now available in Phase 5; production activation remains deferred.
