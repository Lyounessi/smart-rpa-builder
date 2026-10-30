# Technical execution logs

Open a run's Progress page and expand **Technical execution logs**. The latest 50 events refresh with live progress. **Download all logs (JSONL)** exports every recorded event for that run in chronological order, including historical progress events.

New executions record framework browser action start/completion/failure, action name, captured target/application ID, elapsed milliseconds, row and named step. Failures include exception type and up to twelve stack frames (file basename, function and line number), including generated robot code locations when available. Run initialization failures are recorded on the terminal event too. Use the target ID to inspect the frozen build's selector and code.

The run page also highlights the last failed action with a readable timeout/failure summary. Target names come from the frozen build context, so older runs with diagnostics gain readable names without rewriting their history. For generic captured names such as `div`, the configured step/output name is shown. Downloads include these explanations. Code frames preserve both robot entry locations and underlying adapter frames.

Entered values, returned page text, credentials, URLs, raw exception messages, source lines and local variables are excluded from these diagnostics. No arbitrary logging API is exposed to generated robots. These are framework diagnostics, not a complete Python stdout/stderr capture. Existing runs cannot recover diagnostics that were never recorded.

Apply `python manage.py migrate` before running the updated worker/server. Migration `execution.0009_progressevent_diagnostic` adds an optional JSON diagnostic field; existing events retain empty details. No API calls or real email sends are needed to test logging.
