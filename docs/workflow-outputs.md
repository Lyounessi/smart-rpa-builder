# Read text and named row outputs

Choose **Read text → save output** in the project step editor, select the target application and captured element, and enter an output name such as `weather_information`. Names use lowercase letters, numbers and underscores, starting with a letter (64 characters maximum). Each read step in a project has a unique output name. This action does not use an input column.

Outputs and uploaded inputs have separate purposes. Inputs supply data such as `city_name`; outputs hold extracted results such as `weather_information`. Extraction never overwrites `DatasetRow.values`, changes uploaded headers, or creates an input field. Existing projects, input definitions, datasets and configured steps are preserved by additive migrations.

## Framework API

Inside a robot's per-row `process` method:

```python
with ctx.step('get_weather'):
    ctx.assert_visible('CAPTURED_WEATHER_ID')
    weather = ctx.extract_text('CAPTURED_WEATHER_ID', 'weather_information')
    if not weather.strip():
        raise BusinessRejection()
```

`extract_text` uses the existing browser adapter's bounded `read_text` operation, records a plain string in the current row's outputs, and returns that string for explicit business checks. A regular `ctx.read_text` remains available for checks but does not save an output. This extension does not add fixed sleeps or keyboard actions.

Extraction requires an active row before business completion, or the explicit `finalize` phase. It is disallowed during setup/teardown. In `finalize`, values are run outputs rather than row outputs. The same output name can be extracted only once per row or final phase. Each value is limited to 16 KB of UTF-8 and total values to 64 KB per row/final phase. Cancellation is checked through the existing action boundary. These limits do not replace the browser action timeout.

## Persistence and results

Outputs reset before each row and are copied into its `RowResult`. On normal row completion (OK, NOK or ERROR), the queue persists them as `RowAttempt.outputs`. Partial outputs on NOK/ERROR remain associated with that attempt; they do not imply business success. Queue status continues to follow the existing business-completion rules.

`ctx.business_completed()` durably saves the outputs collected so far alongside the business checkpoint. If a later notification fails or execution is interrupted after that checkpoint, the outputs remain and the business operation stays completed. An interruption before any completion event/checkpoint can lose in-memory outputs; no intermediate extraction writes are promised. A subsequent attempt has its own output dictionary and does not overwrite the previous attempt.

The run progress page and Robots → selected run results show saved outputs as escaped text. Progress event logs contain step/status metadata rather than extracted text. Extracted page content can contain sensitive information: choose captures and access to local result data accordingly. CSV/XLSX result export remains deferred.

## Muse

Context includes each step's `output_key`. Framework contract 1.2 documents per-row and final extraction. Assign read steps to per-row processing or final checks and explicitly confirm. Static checks require the configured phase, target and output key and reject using dropdown selection or a plain read as a replacement for saved extraction. Checks do not prove the business success condition.

Contract changes invalidate old source snapshots. Start a fresh review and confirm the updated specification before generating a draft. Generation still never executes or activates source. This change does not introduce direct database writes into generated robots.

For the existing weather project, edit **Get weather** from **Select option** to **Read text → save output**, with an output name such as `weather_information`. Review any old input field that was being used as an output placeholder separately; it is preserved rather than silently deleted. Also ensure the instructions use supported actions and describe recovery as restoring a known page state, rather than saving results. Then create a fresh Muse review.

## Tests

`python manage.py test execution.test_outputs` exercises form/context validation, unique names, static target/output matching, per-row isolation, durable outputs after business success/notification failure, partial failed attempts, HTML escaping, unchanged input values and extraction limits. Tests use fake browser adapters and send no messages or paid Muse requests.
