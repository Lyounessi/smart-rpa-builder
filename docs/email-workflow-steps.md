# Email workflow steps

An email action has an account reference, recipients, a subject and a plain-text body. It does not require a captured element or browser locator. This milestone changes no workflow-editor action choices or existing target validation; the extension is demonstrated in manually authored robot code. Provider selection, account-management UI, OAuth, and a stored email workflow-step form are deferred.

Declare `EmailStep` specifications on the robot so references are validated before setup or business operations:

```python
from robot_framework.base import BaseRobot
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

## Preserve business success separately from notification outcome

After verifying business success, `ctx.business_completed()` atomically persists the row as Done and the attempt's `business_completed_at`, before an optional notification starts. It must only be called once the business operation really succeeded. It is not cancellation-gated: if the robot has observed success, recording that fact takes priority over the next cooperative cancellation check. A saved checkpoint prevents later notification failure, cancellation, or stale-lease recovery from returning the business operation to Pending. It does not eliminate the uncertainty window between an external business operation and its database checkpoint; process-specific idempotency checks are still needed there.

Email actions have a separate `ActionRecord` attached to the row attempt: named step, action type, status, fixed safe diagnostic, and timestamps. No recipients, subject/body or secrets are stored. Named step and email boundary events appear in progress; action records and business checkpoints are visible on the run page and in the read-only admin.

For example, a notification failure can leave **queue: Done; business: completed; row outcome: ERROR; email: uncertain; run: failed** under the default stop-on-error policy. This preserves both facts without repeating the business operation. A started action that never finalizes becomes uncertain during normal cleanup or lease recovery. A unique attempt/step key prevents an accidental second send for the same named action in the same attempt. Notification-only retry/resume is not implemented; rows with checkpoints remain outside the business-processing queue. Workflows without an explicit checkpoint retain the prior Pending/Done rules.

## Run the fake-email example

Use the repository's Python virtual environment, install the existing inspector dependencies and Chromium, and apply migrations as described in the [README](../README.md). No additional email library is required.

Start the deterministic fixture in a separate terminal:

```powershell
.\.venv\Scripts\python.exe manage.py serve_robot_fixture
```

In another terminal, create and run the isolated example:

```powershell
.\.venv\Scripts\python.exe manage.py prepare_robot_demo --with-email
$env:RPA_SECRET_DEMO_USERNAME = 'demo'
$env:RPA_SECRET_DEMO_PASSWORD = 'demo'
# Replace 2 with the dataset ID printed by the preparation command.
.\.venv\Scripts\python.exe manage.py run_robot ROBOT_INVOICE_CHECKS_EMAIL --dataset 2 --fake-email
Remove-Item Env:RPA_SECRET_DEMO_USERNAME, Env:RPA_SECRET_DEMO_PASSWORD
```

This creates a separate Invoice Checks Email project with fictional `name` and `email` values and six UI locator fixtures. Each row verifies its business operation, saves the checkpoint, and performs a named `notify_supplier` action through `FakeEmailAdapter`. The run page shows **simulated**, never delivered. The CLI requires the explicit `--fake-email` flag to select the fake; omitting it leaves email unconfigured and causes notification failure after business success. Existing Invoice Checks projects and datasets are unchanged.

## Architecture and source map

| Component | Responsibility | Source |
|---|---|---|
| Email contract and service | Plain substitution, message validation, adapter protocol and status handling | [email.py](../robot_framework/email.py) |
| Fake adapter | Immediate simulation without authentication or network calls | [adapters/email.py](../robot_framework/adapters/email.py) |
| Context | Injected `ctx.email`, named steps and business checkpoint | [context.py](../robot_framework/context.py) |
| Runner | Validate declared email specifications against schema and rows before browser setup | [runner.py](../robot_framework/runner.py) |
| Database adapter | Atomic checkpoints, action results and interrupted-send recovery | [execution/adapters.py](../execution/adapters.py) |
| Persistence | `RowAttempt.business_completed_at` and per-attempt `ActionRecord` | [execution/models.py](../execution/models.py) |
| Manual example | Verified UI work followed by a notification without a captured email target | [email_example_robot.py](../robots/email_example_robot.py) |

Existing UI action validation remains unchanged. An email action is composed from its account and message fields, while UI actions continue to use captured elements. Adding email configuration to the workflow editor is deferred.

## Verification

Run the email unit and persistence tests without sending messages:

```powershell
.\.venv\Scripts\python.exe manage.py test robot_framework.test_email execution.test_email
```

To include the original and fake-email browser demos:

```powershell
$env:RUN_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe manage.py test execution.tests.BrowserRobotTests
Remove-Item Env:RUN_BROWSER_TESTS
```

Tests cover schema references, one-pass substitution, recipient/header validation, deadline propagation, cancellation, simulated/accepted/failed/uncertain statuses, redacted diagnostics, no automatic retries, and business-checkpoint preservation after failures or abandoned leases. Browser tests use only a deterministic loopback page and the fake email adapter.

## Future Muse generation

Include this guide alongside the [framework contract](robot-framework.md) when assembling a project's future Create RPA context. Generated robots should declare their `EmailStep` specifications, use validated project input keys, and save a verified business checkpoint before optional notifications. Provider authentication and sending implementations belong in injected adapters, never generated business code.

The Create RPA/Muse integration itself, real sending providers, OAuth, account-management screens, attachments, HTML email, and notification-only retry/resume are outside this milestone.
