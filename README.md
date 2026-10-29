# Smart RPA Builder — Powered by Muse

Smart RPA Builder is a web platform designed to help businesses and individuals create robots that automate repetitive work without writing code.

Users will define workflows through screenshots, captured interface elements, and short step-by-step instructions. Meta Muse will use this context to generate robots that run through a Python automation framework.

The planned platform will support inspecting web and Windows desktop applications, running robots, reviewing execution logs, and refining workflows.

> **Status:** Workflow editing, automation briefs, the web inspector, CSV/XLSX datasets, the robot framework/catalog, and budgeted Muse clarification, specification confirmation and statically validated draft generation are implemented. Explicit tests of reviewed Muse drafts are available. Automatic production activation, desktop inspection, OCR, and result exports are deferred.

## Local setup (Windows PowerShell)

Use Python 3.13. The backend uses Django 5.2 LTS and SQLite. Templates use locally bundled HTMX 2.0.11; Node.js and a frontend build are not required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-inspector.lock.txt
.\.venv\Scripts\python.exe -m playwright install chromium
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(50))"
```

Replace `DJANGO_SECRET_KEY` in `.env` with the generated value, then run:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

Open http://127.0.0.1:8000, create a project, add a target application with its starting URL, and add workflow steps. Forms load inline with HTMX and also work as regular pages without JavaScript. Use the up/down buttons to reorder steps.

## Workflow editor

**Run controls:** Each robot page has a prominent **Run robot** button and readiness status. Its HTMX dialog selects a reviewed version, confirmed dataset with pending counts, 1–5 inputs and optional recording. Live progress shows elapsed time, step, processed/outcome counts, **Stop execution / Stopping…**, and links to saved results. See [run controls and draft-testing safeguards](docs/draft-testing.md).

**Input CRUD:** Project input definitions support Add, View, Edit and Delete, with mapped definitions protected. Dataset inputs support Add, View, Edit and recoverable Delete/Restore, plus duplication of completed rows into new pending inputs. Forms use the dataset's saved schema and share upload validation. New executions snapshot their claimed inputs so subsequent edits do not change prior results. See [manual input management and history preservation](docs/manual-inputs.md).

**Phase 5:** Reviewed draft versions can now be explicitly tested on 1–5 pending input rows from their version page. Test history, saved outputs and timing KPIs remain linked to that version; drafts are not automatically activated. See [draft testing, CLI and the isolated greeting demo](docs/draft-testing.md). Testing runs trusted reviewed Python with local permissions; static checks are not a sandbox.

Steps support **Read text → save output** with a named result such as `weather_information`. Extracted text is stored per row attempt and displayed in run results, separately from uploaded input values. See [workflow outputs and framework API](docs/workflow-outputs.md). Muse uses framework contract 1.1; older confirmations require a fresh review. Generated drafts can now be explicitly tested from their version page; production activation remains deferred.

- One project represents one workflow, with a name and optional description.
- Project creation and editing include an application setup: web application or multiple applications (web only for now). Desktop is visible but disabled and rejected server-side until desktop support is implemented. Existing projects default to web. This setup describes workflow intent; application windows remain separate reusable entities, and it does not impose a window-count limit.
- Target applications store a name and HTTP(S) starting URL. Embedded URL credentials are rejected; do not put passwords or tokens in URLs.
- Steps store a name, plain-language instruction, ordered position, and optional application reference. Navigation steps need no captured element.
- Projects, applications, and steps can be edited. Changes persist in SQLite and are retrieved after restarting Django.
- Captured elements store UUIDs, versioned structured locators, semantic metadata, capture URL, frame and coordinate context, validation details, and screenshot file references.
- Steps link to elements through a separate reference table, allowing element reuse and multiple references later. The current editor supports zero or one target and restricts choices to the current project and selected application.
- A capture URL describes where an element was captured; the application starting URL describes where to launch. Neither automatically creates a navigation instruction.
- Reordering uses transactional position swaps with a per-project uniqueness constraint. This is a local single-user editor; simultaneous multi-user editing is outside the MVP scope.
- Project/step deletion and desktop inspection are not available. The database reserves the desktop application type; the UI creates web applications only.
- The local editor has no sign-in requirement in this milestone. Django admin uses its normal authentication. Keep the server bound to loopback.

## Project inputs and datasets

1. Open a project and choose **Add input**. Define keys such as `supplier_name` and `document_type`, their description, text/number type, and whether a value is required. Keys use lowercase letters, digits and underscores, starting with a letter; they are unique per project. Reference the same keys in workflow instructions.
2. Choose **Upload input file**, name the dataset, and upload UTF-8 comma-separated CSV or a single-worksheet `.xlsx` workbook.
3. The first row must contain every defined input key exactly once, with no additional columns. Column order can differ. Required means each record needs a non-empty value; optional columns must still have headers.
4. Review the paginated table (50 records per page). Empty required values and invalid numbers show errors. Edit invalid pending rows in the dataset, or correct your source file and upload a new dataset.
5. Choose **Confirm dataset** when all records are valid. The dataset becomes ready for registered robots; confirmation alone executes nothing. Reopen it from the project's dataset list after restarting Django.

Limits: 2 MB uploaded file, 1,000 data rows including blank rows, 30 inputs/columns, and 2,000 characters per cell. Completely blank rows are skipped. CSV uses UTF-8 (BOM accepted), commas and standard quoting. XLSX formulas and error cells are rejected; paste values before uploading. Multiple worksheets, legacy `.xls`, macros, encrypted workbooks, column mapping, bulk deletion, and result downloads are outside this milestone. Individual input CRUD is available as described above.

Cells and headers are trimmed. Text identifiers preserve leading zeros when supplied as text; Excel numeric formatting is not preserved, so store identifiers as text cells. Numbers must be finite, at most 30 digits, with a decimal point and no thousands separators. Decimal values are stored as strings with the number type in the schema to avoid floating-point precision loss. Optional empty values are empty strings.

Parsed rows and a snapshot of their input definitions are stored in SQLite; the original upload is not retained. Later input edits do not rewrite historical datasets. The preview warns when current project definitions differ from its snapshot. Dataset preview/ready states describe preparation; row processing states and attempts are tracked separately by the runner. CSV/XLSX result exports remain deferred.

Never upload credentials. Importing does not evaluate formulas or execute CSV cell content. Read-only Django admin views are available for input definitions, datasets and rows. Both runtime lock files include the XLSX reader and XML parser protection.

Optional Django admin account:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

`accounts.User` extends `AbstractUser` and is configured before the initial migration. Registration and role screens are deferred.

## Environment and dependencies

- `.env.example` documents local settings; `.env` is ignored by Git. Existing environment variables take precedence over the file.
- A secret key is required. Debug defaults to false; the example enables it for local development. Keep this single-user development server bound to loopback.
- SQLite is stored in `db.sqlite3`; captures go into `media/`. Both are ignored by Git. Back up both together.
- `requirements.txt` allows patch updates within Django 5.2 LTS. `requirements.lock.txt` records the exact verified runtime dependencies; install it instead for a reproducible environment.
- `requirements-inspector.txt` adds Playwright and Pillow. `requirements-inspector.lock.txt` pins the complete verified inspector environment. Install Chromium separately with the command above.
- HTMX is vendored in `static/vendor/` with its license. Django retains CSRF protection; future mutation forms must include `{% csrf_token %}`. `static/app.js` forwards that token for same-origin HTMX requests.
- Normal workflow/inspector/runner features need no Muse key. The backend connection check and explicit project reviews use `MUSE_APIKEY` from the local environment; see [Muse setup](docs/muse-integration.md). Never commit actual credentials or include them in model context.

## Muse API connection (Phase 1)

Set `MUSE_APIKEY` in your ignored `.env`, optionally set `META_MODEL` (default `muse-spark-1.3`) and `META_TIMEOUT_SECONDS` (default 45), then run `python manage.py check_muse_connection` through the project's virtual environment. This explicitly makes one small paid request with a fixed prompt, a 128-token output cap, and SDK retries disabled. It sends no project data and never executes a robot.

See [configuration, safe errors, tests and current limits](docs/muse-integration.md). The API key stays backend-only, and no connection check runs automatically.

### Context and spending controls (Phase 2)

`python manage.py prepare_muse_context <project_id>` saves a filtered local snapshot with a compact versioned Markdown contract, one example, project JSON and deduplicated referenced screenshots. It sends nothing to Meta. Specification and image-content hashes detect changes before and during a request; stale responses are discarded.

All application API calls, including the explicit connection check, now use a persistent usage ledger and conservative reservations. The default local limit is $140 of the $150 hackathon allowance, configurable with `MUSE_BUDGET_USD`; one Muse operation is active at a time. Unknown usage retains its full reservation. Open **Muse usage** (`/muse/usage/`) to inspect estimates and commitments. These are local estimates, not a provider billing guarantee or account balance.

Apply migrations first. See [context composition, limits, pricing configuration, recovery and tests](docs/muse-context-budget.md). No real API call is needed to prepare context or view usage.

### Build with Muse (Phases 3–4)

Open a project and choose **Build with Muse**. An explicit paid review runs in a background process; the page polls persisted progress. Muse asks at most three questions per reply, with three review attempts per session including the initial review. Proposed changes require confirmation, and user answers become structured robot specification decisions. Local specification editing and final confirmation make no API call.

See [conversation workflow, supported changes, limits, worker recovery and tests](docs/muse-conversation.md). The initial review includes referenced screenshots; follow-ups omit images unless requested. Old messages and unresolved questions are preserved, stale context/forms are blocked, and all paid calls use the existing usage/budget service. After confirmation, **Generate draft robot** creates a new version with static checks and at most two budgeted repairs. Generated code is never imported, activated or executed in this phase. See [draft generation, validation and recovery](docs/muse-generation.md).

## Checks

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
```

## Web inspector

1. Create a project, a web application with its starting URL, and a step with an instruction and application selected.
2. Save the step, then choose **Capture / test target**.
3. Choose **Open inspection browser**. A separate visible Chromium browser opens; navigate or log in manually.
4. Choose **Inspect element** in Django or **Select element** in the browser toolbar. Hover to highlight, then click to capture without the ordinary click action. Escape or **Cancel selection** returns to browsing.
5. Return to Django to review the highlighted viewport and element crop. Name the element and choose **Save target to step**, or discard it. Recapturing replaces only the unsaved draft. The browser remains open during review and saving.
6. Choose **Test saved locator** to check the current page. The result distinguishes missing, ambiguous, hidden, and one visible match; a unique visible match is highlighted. Results are timestamped historical checks, not a guarantee of future validity.
7. **Stop inspector** in either interface closes Chromium and ends the worker. Manual browser closure also ends the session.

The toolbar can be moved between the top and bottom of the page if it covers a target. It is excluded from screenshots. Only one inspection browser runs at a time. Opening another step for the same project and application reuses the browser when no operation is in progress; draft captures retain their original step. Stop before switching applications or projects.

Saved targets and screenshot files survive restarting Django. Open the browser again, navigate to the relevant page, and test the saved locator. Navigation is manual; a capture URL does not automatically drive browser navigation.

### Process and persistence

Django launches `manage.py inspect_browser` as one child process. Its async Playwright loop owns the visible browser, services toolbar events, and reads fixed commands from SQLite. Django serves HTML and polls session status through HTMX every two seconds. Short database transactions keep browser operations outside database locks. Pending non-stop commands expire after 30 seconds and are not retried automatically.

The worker checks the local server's session health endpoint every two seconds. Three failed checks close the browser, including after the server process restarts. Worker heartbeats allow Django to mark stale sessions interrupted after 30 seconds. Screenshots and saved targets remain intact. Use one Django server process; automatic reloads intentionally interrupt inspection, so `--noreload` is recommended while capturing.

A selection produces a draft tied to its exact step. Saving creates a reusable element UUID and attaches it transactionally, replacing the current step reference. The previous saved element remains available for reuse. Draft recapture/discard deletes that draft's images; saved images are retained. Unsaved drafts survive a stopped session for review and occupy local media space until saved, replaced, or discarded.

### Privacy and limits

- Screenshots mask inputs, textareas, editable regions, and embedded surfaces before the image is persisted. The element crop is cut from the same masked viewport image. Input values, cookies, browser storage, full HTML, and authentication state are not exported. Browser contexts are ephemeral; log in again after reopening.
- Masking is not complete secret detection: ordinary text, labels, page paths, images, or custom controls may contain sensitive information. Review both screenshots and discard unsuitable captures. Automatically recorded capture URLs omit user information, query strings, and fragments. Never enter actual secrets into workflow instructions or target URLs.
- Selectors prefer test IDs, roles and associated labels, then allowlisted semantic attributes (including Angular field names), ID/descriptive attributes, classes and bounded parent context. An ID is not required; see [selector fallbacks and RPA Challenge](docs/inspector-selectors.md). Version 1 definitions use `strategy` plus `role`/`name` or `value`; the resolver is in `inspector/locators.py`. No absolute XPath or positional fallback is generated. Some controls cannot produce a unique stable selector and require another selection.
- Each new capture stores `selector_quality` alongside the locator for future Muse context: an ID-pattern assessment, a semantic identity baseline, and a bounded history of successful document/session observations. Suspected generated IDs are skipped during candidate selection. Pattern checks are heuristics, not proof. Repeated tests in one document do not increase stability evidence. Successful identity checks across manual reloads or browser reopenings are labelled `observed_across_documents`; mismatches and failed tests require review. Unlabelled controls may lack enough semantic evidence to verify identity. Existing captures remain unverified until recaptured. Saved-locator tests never automatically reload or navigate. OCR remains deferred; saved selector evidence is included in Muse context.
- Only the main document of the original tab is supported. New tabs/popups are closed; iframe internals, closed shadow roots, canvas, embedded viewers, and complex custom controls are excluded. OCR and visual targeting are future possibilities, not active fallbacks.
- Click interception is best effort for ordinary HTML controls. Browser-native UI and unusual application event handlers are outside the MVP guarantee. Work on non-critical pages when capturing.
- The target browser must run in the interactive Windows host session. Docker/headless hosting, multi-user inspection, and production deployment are outside this milestone.
- Muse clarification now receives filtered ordered instructions, element IDs, highlighted screenshots and structured selectors with a compact framework contract. Confirmed specifications can generate drafts, followed by explicit reviewed tests. Production activation remains deferred. No RAG or vector database is used.

### Browser checks

The standard suite runs database, review, project-boundary, ordering, and lifecycle-state tests without launching browsers. To also run real Chromium selection/masking and visible-browser start/stop/disconnect checks:

```powershell
$env:RUN_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe manage.py test
Remove-Item Env:RUN_BROWSER_TESTS
```

## Hackathon Contributions

### Project automation brief

Projects support an optional **Automation brief**: Goal, Global rules and Success criteria (up to 5,000 characters each). Set these when creating/editing a project or use the dedicated Add/Edit automation brief button on its detail page. Existing projects remain valid with all fields empty; briefs can also be cleared. Keep credentials out of these fields.

`projects.generation_context.assemble_generation_context(project, framework_contract=...)` prepares structured context for Muse. User-authored project data, including the brief, is separate from platform instructions and the supplied framework contract. It includes ordered step instructions, input definitions/mappings, target applications and only referenced saved elements, with locator evidence and screenshot references. It excludes dataset row values and sends nothing externally on its own. Structured project outcome/exception-rule arrays remain empty; confirmed build-session decisions supplement them without inferring configuration from past results.

The brief supplements explicit steps and does not change their targets, mappings or execution settings. Identified contradictions require clarification rather than a silent interpretation. In the conversation schema this is `state=needs_clarification` with targeted questions. This is not a guarantee that every conflict can be found. Actual step edits require explicit proposal confirmation; draft generation requires explicit specification confirmation.

### Python robot framework

The [Robots catalog](docs/robot-catalog.md) at `/robots/` shows registered versions, run history, treated inputs, separate business/notification results and timing KPIs. Runs keep their saved build reference. Use `python manage.py sync_robot_catalog` to register existing manual demo projects without executing them. Muse drafts are versioned in the catalog and clearly marked as not activated.

The framework also exposes an injected email adapter for non-UI steps. The fake-only email demo validates simple input substitutions, records named email outcomes, and saves a business-success checkpoint so notification failure cannot repeat completed work. See the [email workflow steps guide](docs/email-workflow-steps.md) for the API, checkpoint behavior, fake-only demo, and tests. No real provider, OAuth, or email account UI is included.

The first framework version runs an explicitly registered robot by name against pending rows in a confirmed dataset. It persists progress, row attempts and queue status, supports cooperative cancellation, and optionally records browser-page video. The framework owns lifecycle and resources; robot code owns login, business actions, success checks and recovery. Muse draft generation is available from Build with Muse; running generated drafts remains a later milestone.

See [framework API, runnable local demo, commands, and limitations](docs/robot-framework.md). Start with `python manage.py prepare_robot_demo`, run `python manage.py serve_robot_fixture` in another terminal, then use the printed dataset ID with `python manage.py run_robot ROBOT_INVOICE_CHECKS --dataset <id>`. The example's fictional login secrets must be configured as described in that document.

### Step input mappings

In the step editor, choose **Click**, **Fill**, or **Select option**. Fill and Select option require an **Input column** from the current project's process inputs (for example `name`). This stores a reference to the input definition, so the future runner can use that column's value from each dataset row. Click clears the input mapping. Captured targets remain optional while drafting a step.

Existing steps retain their instructions and targets and show **Choose an action** until edited. Referenced input definitions cannot be deleted. Actions and mappings are visible in the workflow and Django admin, available to the runner and included in Muse context.

This project is being built during the hackathon, from October 26 to November 4, 2026. Implemented features and setup instructions will be added as development progresses.

## License

This project is licensed under the [MIT License](LICENSE).
