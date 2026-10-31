# Pending inputs and treatment results

Open a project and choose **Results and treatment dates**, or use **Treated results** from a robot or dataset. Dataset input tables show pending and in-progress records only. Treated records stay stored in the same dataset and keep their history; they are not moved, erased or reprocessed automatically. Deleted inputs retain their historical results too.

Each result is a `RowAttempt` for one dataset record, never a workflow action. Ten source records produce ten attempts even when many Fill/Submit actions are logged. Results display the original input snapshot, separate extracted outputs, outcome, treatment timestamp, duration, run and robot version. Run-level final verification outputs remain attached to the run. Repeated attempts are separate historical facts.

Filter by treatment/attempt date range (both endpoints inclusive), dataset, run and robot version. The default is confirmed treatments (`business_completed_at` or historical OK outcome). Business-completion timestamps are preferred; historical OK attempts can use their recorded finish timestamp. Missing historical timestamps/inputs are not reconstructed. Dates use the configured Django timezone, shown beside the filters. In unconfirmed/all mode, non-treated attempts use their attempt finish/start/creation timestamp for date filtering. Invalid filters produce validation errors instead of silently showing unfiltered results.

## Submission versus verification

A completed Click is not proof that the application accepted a record. When a later visibility/text/value/progress check fails in the same named step and record, the UI and downloadable logs explain: **the click completed, but its subsequent success check failed; the external outcome is unconfirmed**. Check the application before retrying. This explanation uses recorded evidence without rewriting the outcome or marking a pending record treated.

The saved RPA Challenge v3 recorded nine OK attempts and a tenth ERROR at the Submit verification: it waited for the First Name field, which can disappear on final completion. The intended successful pattern is to capture the round/status text before Submit and wait for either a changed round or the captured completion target, then verify final Congratulations once. The framework already supports the bounded `ctx.wait_for_progress` action. No runtime fallback, automatic Submit retry, old-source rewrite, paid generation, or historical success backfill is introduced here. Existing version 3 must be updated through a new reviewed robot version to change its behavior.

No schema migration is required: treatment timestamps and snapshots are already recorded. Local tests reproduce both nine-OK/one-unconfirmed behavior with the incorrect final check and ten treated records with the completion-aware check, while preserving input count and run-level outputs. CSV/XLSX results export is deferred.
