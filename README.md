# Smart RPA Builder — Powered by Muse

Smart RPA Builder is a web platform designed to help businesses and individuals create robots that automate repetitive work without writing code.

Users will define workflows through screenshots, captured interface elements, and short step-by-step instructions. Meta Muse will use this context to generate robots that run through a Python automation framework.

The planned platform will support inspecting web and Windows desktop applications, running robots, reviewing execution logs, and refining workflows.

> **Status:** Workflow editing, the local web inspector, project input definitions, and CSV/XLSX dataset preview are implemented. Desktop inspection, OCR, Muse integration, robot execution, and result exports are deferred.

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
4. Review the paginated table (50 records per page). Empty required values and invalid numbers show errors. Correct your source file and upload a new dataset if any rows are invalid.
5. Choose **Confirm dataset** when all records are valid. The dataset becomes ready for the future runner; no robot executes in this milestone. Reopen it from the project's dataset list after restarting Django.

Limits: 2 MB uploaded file, 1,000 data rows including blank rows, 30 inputs/columns, and 2,000 characters per cell. Completely blank rows are skipped. CSV uses UTF-8 (BOM accepted), commas and standard quoting. XLSX formulas and error cells are rejected; paste values before uploading. Multiple worksheets, legacy `.xls`, macros, encrypted workbooks, column mapping, in-app record editing, deletion, and result downloads are outside this milestone.

Cells and headers are trimmed. Text identifiers preserve leading zeros when supplied as text; Excel numeric formatting is not preserved, so store identifiers as text cells. Numbers must be finite, at most 30 digits, with a decimal point and no thousands separators. Decimal values are stored as strings with the number type in the schema to avoid floating-point precision loss. Optional empty values are empty strings.

Parsed rows and a snapshot of their input definitions are stored in SQLite; the original upload is not retained. Later input edits do not rewrite historical datasets. The preview warns when current project definitions differ from its snapshot. Dataset preview/ready states describe data preparation, not robot execution outcomes. Future execution will add per-row results and CSV/XLSX result exports.

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
- No Muse API key is needed at this stage. Never commit actual credentials or include them in model context.

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
- Selectors prefer test IDs, roles with accessible names, and labels, followed by stable attribute CSS selectors or exact text. Version 1 definitions use `strategy` plus `role`/`name` or `value`; the resolver is in `inspector/locators.py`. No absolute XPath or positional fallback is generated. Some controls cannot produce a unique stable selector and require another selection.
- Each new capture stores `selector_quality` alongside the locator for future Muse context: an ID-pattern assessment, a semantic identity baseline, and a bounded history of successful document/session observations. Suspected generated IDs are skipped during candidate selection. Pattern checks are heuristics, not proof. Repeated tests in one document do not increase stability evidence. Successful identity checks across manual reloads or browser reopenings are labelled `observed_across_documents`; mismatches and failed tests require review. Unlabelled controls may lack enough semantic evidence to verify identity. Existing captures remain unverified until recaptured. Tests never automatically reload or navigate, and no OCR fallback or Muse integration is enabled.
- Only the main document of the original tab is supported. New tabs/popups are closed; iframe internals, closed shadow roots, canvas, embedded viewers, and complex custom controls are excluded. OCR and visual targeting are future possibilities, not active fallbacks.
- Click interception is best effort for ordinary HTML controls. Browser-native UI and unusual application event handlers are outside the MVP guarantee. Work on non-critical pages when capturing.
- The target browser must run in the interactive Windows host session. Docker/headless hosting, multi-user inspection, and production deployment are outside this milestone.
- Muse integration is deferred. The future context will include ordered instructions, element IDs, highlighted screenshots, and structured selectors, together with framework documentation. No RAG or vector database is used.

### Browser checks

The standard suite runs database, review, project-boundary, ordering, and lifecycle-state tests without launching browsers. To also run real Chromium selection/masking and visible-browser start/stop/disconnect checks:

```powershell
$env:RUN_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe manage.py test
Remove-Item Env:RUN_BROWSER_TESTS
```

## Hackathon Contributions

This project is being built during the hackathon, from October 26 to November 4, 2026. Implemented features and setup instructions will be added as development progresses.

## License

This project is licensed under the [MIT License](LICENSE).
