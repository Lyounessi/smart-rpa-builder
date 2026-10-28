# Robot framework v1

This is the execution contract for manually authored robots and future Muse generation. The web app's future **Create RPA** button will assemble project details, ordered steps, input definitions/mappings, target application URLs, captured element IDs, locator definitions, reviewed highlighted screenshots, this document, and the example robot. Generation is not implemented here. Dataset values and actual credentials are not generation context by default.

## Robot identity and trust

`robot_framework.registry.robot_name('Invoice Checks')` returns `ROBOT_INVOICE_CHECKS`. Punctuation and spaces become underscores and letters become uppercase. Normalization can collide, so registration rejects duplicate names. Future generation must reject project-name collisions and require review before adding generated code to the trusted registry. Renaming a project does not migrate existing run records.

Only explicitly registered Python classes execute. CLI input never supplies an import path. The registry contains the manually authored Invoice Checks and Invoice Checks Email examples, bound to the matching project's fixture targets. A project definition alone is not an executable robot.

## Core API

The core modules (`contracts`, `context`, `base`, `runner`, `registry`) have no Django dependency. Browser, secrets, event sink, and cancellation objects are injected into `Runner`. The Django command is one integration adapter; core tests use fakes.

```python
from robot_framework.base import BaseRobot
from robot_framework.contracts import BusinessRejection

class ExampleRobot(BaseRobot):
    def setup(self, ctx):
        with ctx.step('login'):
            ctx.navigate('application-id')
            ctx.fill('captured-username-id', ctx.secrets.get('PORTAL_USERNAME'))
            ctx.fill('captured-password-id', ctx.secrets.get('PORTAL_PASSWORD'))
            ctx.click('captured-sign-in-id')
            ctx.assert_visible('captured-form-id')

    def process(self, ctx, inputs):
        with ctx.step('create_record'):
            ctx.fill('captured-name-id', inputs['name'])
            ctx.select_option('captured-document-type-id', inputs['document_type'])
            ctx.click('captured-submit-id')
            ctx.assert_visible('captured-status-id')
            if ctx.read_text('captured-status-id') != 'Accepted':
                raise BusinessRejection()

    def teardown(self, ctx):
        pass
```

Use actual captured UUIDs and application IDs injected for the project, not CSS strings in robot code. `navigate` resolves an application ID to its configured starting URL. `fill`, `click`, `select_option` (native HTML selects), `read_text`, and `assert_visible` resolve captured IDs through the existing inspector locator representation. Strict Playwright actions reject ambiguous locators; assertions wait and explicitly fail. Captured URL metadata is not automatic navigation. Waits are bounded by `RunOptions.action_timeout_ms` (default 10 seconds, maximum 120 seconds). No fixed sleep synchronization.

The base class owns lifecycle ordering. Implement `setup`, `process`, optional `recover`, and `teardown`; do not override `execute`. `process` returning normally means the robot has explicitly verified business success. Throw `BusinessRejection` for a known rejection, other exceptions for technical failure. Never include input values or secrets in diagnostic text, step IDs, or exception messages. Built-in persistence uses fixed messages and does not save raw exceptions. The original primary exception is retained only in the in-memory `RunResult.primary_error`, excluded from its repr; teardown failures are separate.

`recover(ctx, outcome)` defaults to False. If continuing after NOK/ERROR and more rows remain, the robot must restore a known application state and return True. Otherwise execution stops as failed. The framework never retries a row or submission. Robot logic must check external record identifiers to avoid duplicate effects on a later run after an uncertain failure.

Cancellation checks occur before setup, rows, named steps, and browser actions, and after processing before recording success. During teardown, cancellation checks are disabled so cleanup can proceed. An action already running is bounded by its timeout, not immediately interrupted. Teardown must tolerate partial setup. Framework cleanup attempts context close, browser close, and Playwright shutdown independently after robot teardown.

## Queue and run persistence

`DatasetRow.processing_status` is pending, in_progress, or done. Only confirmed datasets without validation errors and with pending rows can start. A run snapshots the pending row references and values into memory; do not mutate datasets during execution. Each selected row is claimed atomically immediately before processing. One unique active-run slot prevents concurrent robot runs against this local database. Browser operations use a dedicated thread because Playwright's synchronous API owns an event loop; Django's synchronous ORM stays on the command thread.

OK returns the row to Done. NOK and ERROR return it to Pending while retaining a `RowAttempt` outcome, fixed diagnostic, and failed step, unless the robot has already persisted a business-success checkpoint (see email steps below). Interrupted/cancelled attempts without a business-success checkpoint retain an unconfirmed outcome and return to Pending. Rows are never retried within the same run. Preview/invalid rows are never processed. Results and queue state are separate.

Run states are queued, running, completed, failed, cancelled. Completed may include NOK/ERROR if continuation policy and recovery permitted it. Persisted outcome counts distinguish that from universal success. Stop-on-NOK ends completed with an explicit stop reason and unprocessed references. Stop-on-ERROR ends failed. Teardown/resource cleanup failure makes an otherwise completed run failed and preserves original execution failure when present.

Progress events include run, row, step, setup, and teardown boundaries. Database writes use short transactions at boundaries and contain no row values, credentials, raw browser errors, or stack traces. Run detail polls every two seconds while active. Cancellation is a POST from that page or Ctrl+C in the command. Results are inspectable in the read-only admin as well.

A heartbeat updates every five seconds; failure to renew triggers cooperative cancellation. After 120 seconds without a heartbeat, the next start recovers the abandoned run and returns unfinished rows without a business-success checkpoint to Pending. Rows with a saved checkpoint remain Done. Recovery cannot prove whether an external submission completed before a checkpoint was saved: check the target application's state before retrying. Hard termination cannot guarantee application teardown, recording finalization, or immediate orphan-browser cleanup. Lease recovery is local and not a distributed VM orchestration system. The inspector's separate active slot is unchanged; close it before running a robot to avoid confusion.

## Non-UI email steps (fake provider only)

An email action has an account reference, recipients, a subject and a plain-text body. It does not require a captured element or browser locator. This milestone changes no workflow-editor action choices or existing target validation; the extension is demonstrated in manually authored robot code. Provider selection, account-management UI, OAuth, and a stored email workflow-step form are deferred.

Declare `EmailStep` specifications on the robot so references are validated before setup or business operations:

```python
from robot_framework.email import EmailStep

class SupplierRobot(BaseRobot):
    notification = EmailStep(
        step_id='notify_supplier',
        account='notifications',
        to='{{email}}',
        subject='Supplier {{supplier_name}} created',
        body='Your supplier registration is complete.',
    )
    email_steps = (notification,)

    def process(self, ctx, inputs):
        # Perform and explicitly verify the business operation here first.
        ctx.business_completed()
        ctx.email.send_step(self.notification, inputs)
```

The Django runner passes the confirmed dataset's saved schema to preflight validation. Every referenced key must exist in that schema and every selected row. Recipients and headers are validated for all selected rows before the browser opens. A caller using the core directly should supply `runner.run(..., input_fields=validated_schema_keys)`; without that argument the core uses keys present in every supplied row.

Substitution supports only `{{input_key}}` (optional whitespace inside braces). Python expressions, attribute access, template filters, loops and template comments are rejected. Values are substituted once and are never interpreted again. Bodies remain plain text. The initial address validator accepts plain recipient addresses, either comma-separated or as a list; display-name headers and CR/LF in recipients or subjects are rejected. Rendered message content is neither persisted nor logged. The message dataclass also hides recipients, subject and body from its repr.

For manually written business code, the lower-level API is also available inside a named row step:

```python
with ctx.step('notify_supplier'):
    ctx.email.send(
        account='notifications',
        to=inputs['email'],
        subject=f"Supplier {inputs['supplier_name']} created",
        body='Your supplier registration is complete.',
    )
```

This lower-level call validates the rendered message before invoking an adapter. It cannot inspect arbitrary Python expressions to discover field usage ahead of time; use declared `EmailStep` specifications for schema preflight and for future generated configuration. Fixed step IDs and account references must contain no input values or secrets.

`Runner(..., email=adapter)` injects an implementation of the core `EmailAdapter` protocol. The adapter receives an `EmailMessage` and `timeout_seconds`, and returns accepted, failed, uncertain, or simulated. Accepted means provider acceptance, not proof of inbox delivery. Simulated means no real message was sent. A known failure before provider acceptance can report failed; unexpected exceptions, timeouts, interrupted sends, and abandoned started actions are conservatively uncertain. There is no automatic send retry. Cancellation is checked before sending; an in-flight operation is bounded by the adapter deadline and is not promised to cancel immediately.

Each real provider adapter must enforce the supplied end-to-end network deadline (default 15 seconds; configurable with `--email-timeout-seconds`, maximum 120), manage/close its own connections, resolve account/secret references internally, avoid exposing provider exception text, and disable internal automatic retries for uncertain submissions. The core cannot make an arbitrary adapter obey a timeout. The shipped fake returns immediately and performs no network calls, authentication, or secret lookup. With no adapter configured, a send fails explicitly; it is never silently treated as sent.

SMTP, Microsoft Graph, Gmail API, and Outlook desktop are different providers with different authentication and dependencies. None is implemented or assumed interchangeable. A chosen provider's libraries must be added explicitly to dependency manifests/locks. The runner never invokes pip or installs dependencies.

### Preserve business success separately from notification outcome

After verifying business success, `ctx.business_completed()` atomically persists the row as Done and the attempt's `business_completed_at`, before an optional notification starts. It must only be called once the business operation really succeeded. It is not cancellation-gated: if the robot has observed success, recording that fact takes priority over the next cooperative cancellation check. A saved checkpoint prevents later notification failure, cancellation, or stale-lease recovery from returning the business operation to Pending. It does not eliminate the uncertainty window between an external business operation and its database checkpoint; process-specific idempotency checks are still needed there.

Email actions have a separate `ActionRecord` attached to the row attempt: named step, action type, status, fixed safe diagnostic, and timestamps. No recipients, subject/body or secrets are stored. Named step and email boundary events appear in progress; action records and business checkpoints are visible on the run page and in the read-only admin.

For example, a notification failure can leave **queue: Done; business: completed; row outcome: ERROR; email: uncertain; run: failed** under the default stop-on-error policy. This preserves both facts without repeating the business operation. A started action that never finalizes becomes uncertain during normal cleanup or lease recovery. A unique attempt/step key prevents an accidental second send for the same named action in the same attempt. Notification-only retry/resume is not implemented; rows with checkpoints remain outside the business-processing queue. Workflows without an explicit checkpoint retain the prior Pending/Done rules.

### Run the fake-email example

Keep the same local fixture server running, then:

```powershell
.\.venv\Scripts\python.exe manage.py prepare_robot_demo --with-email
$env:RPA_SECRET_DEMO_USERNAME = 'demo'
$env:RPA_SECRET_DEMO_PASSWORD = 'demo'
# Replace 2 with the dataset ID printed by the preparation command.
.\.venv\Scripts\python.exe manage.py run_robot ROBOT_INVOICE_CHECKS_EMAIL --dataset 2 --fake-email
Remove-Item Env:RPA_SECRET_DEMO_USERNAME, Env:RPA_SECRET_DEMO_PASSWORD
```

This creates a separate Invoice Checks Email project with fictional `name` and `email` values and six UI locator fixtures. Each row verifies its business operation, saves the checkpoint, and performs a named `notify_supplier` action through `FakeEmailAdapter`. The run page shows **simulated**, never delivered. The CLI requires the explicit `--fake-email` flag to select the fake; omitting it leaves email unconfigured and causes notification failure after business success. Existing Invoice Checks projects and datasets are unchanged.

## Browser video and secrets

`--record-screen` records **browser-page video**, not the Windows desktop. Playwright starts it with the context and finalizes it on context close. Video paths are stored on the run under ignored `media/runs/<run-id>/`. Video may include credentials, input values, and sensitive page content; it is not masked. It is never sent to Muse automatically or publicly served by this milestone. Keep recording off for sensitive workflows. Automatic error screenshots are deliberately not captured; video is the optional evidence artifact. Video references are run-level, not per-row clips.

The initial secret provider reads `RPA_SECRET_<REFERENCE>` from the local process environment (`.env` is loaded by Django). `ctx.secrets.get('PORTAL_PASSWORD')` resolves `RPA_SECRET_PORTAL_PASSWORD`. Missing secrets fail without revealing values. This provider is a development mechanism, not a credential vault. Replace it with Windows Credential Manager or a VM secrets provider through injection later. Actual credentials never belong in robots, commands, project instructions, registry mappings, or Git.

## Local example

Install existing inspector dependencies and Chromium as described in the README, migrate, then run these in separate terminals:

```powershell
# Terminal 1: loopback fixture, no shared external service
.\.venv\Scripts\python.exe manage.py serve_robot_fixture
```

```powershell
# Terminal 2: create a new isolated demo (refuses to overwrite an existing project)
.\.venv\Scripts\python.exe manage.py prepare_robot_demo
$env:RPA_SECRET_DEMO_USERNAME = 'demo'
$env:RPA_SECRET_DEMO_PASSWORD = 'demo'
# Replace 1 with the dataset ID printed by prepare_robot_demo
.\.venv\Scripts\python.exe manage.py run_robot ROBOT_INVOICE_CHECKS --dataset 1 --record-screen
Remove-Item Env:RPA_SECRET_DEMO_USERNAME, Env:RPA_SECRET_DEMO_PASSWORD
```

Keep the Django server running to view the printed `/execution/<run-id>/` URL, or open the demo project's dataset to see runs. The worker itself does not depend on a running web server. The fixture is deliberately fictional, with minimal demo authentication; it is not a real invoice system. It seeds six locator fixtures with generated element UUIDs (not screenshot captures), a `name` input, and two ready rows. A value of `Reject` demonstrates business rejection. Successful rows remain Done and are not selected on a later run. Use another confirmed dataset in the demo project to execute fresh rows.

CLI options: `--record-screen`, `--stop-on-nok`, `--continue-on-error`, `--action-timeout-ms`, `--email-timeout-seconds`, `--fake-email`. Technical errors stop by default. Robot recovery remains mandatory when continuing. Failed and cancelled commands exit nonzero; completed commands exit zero even if permitted NOK/ERROR outcomes exist, so inspect run counts.

## Tests and limits

```powershell
.\.venv\Scripts\python.exe manage.py test robot_framework execution projects
$env:RUN_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe manage.py test robot_framework execution inspector projects
Remove-Item Env:RUN_BROWSER_TESTS
```

Fake-adapter tests cover lifecycle, row outcomes, continuation/recovery, cancellation, partial setup, teardown preservation, invalid registry names, and recording/resource cleanup. Email tests cover one-pass substitution, schema preflight, message validation, bounded-timeout propagation, redacted diagnostics, accepted/simulated/failed/uncertain results, no retries, checkpoint preservation, cancellation, and lease recovery. No test sends real email. Database tests cover claims, outcome persistence, cancellation, expired leases, and active-run exclusion. Real-browser smoke tests use a loopback fixture, two rows, real saved locator UUIDs, persisted progress/results, and finalized nonempty WebM output for the original robot and fake-email extension.

This version supports one local visible Chromium session per run, one original page, and sequential rows. Unknown dialogs/popups cause failure and are not dismissed. MFA/CAPTCHA, desktop automation, schedules, multi-VM workers, exports, Create RPA UI, Muse calls, automatic code installation, and production credential management are deferred.
