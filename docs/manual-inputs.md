# Manual dataset inputs

On a project, **Create dataset manually** creates an empty preview using the project's current input definitions. Give it a name, use **Add input** to enter a valid row, then confirm the dataset when ready. No file or API call is needed. Project input definitions must exist first.

Every dataset page now offers **Add input**. Pending, unclaimed rows offer **Edit**; completed, released rows offer **Duplicate as new pending input**. In-progress rows and rows still claimed by an execution stay locked, including a completed business operation whose notification is still processing. Duplication opens a prefilled form; the original completed input and its history stay unchanged. GET requests never insert or modify rows.

Forms always use the dataset's saved schema, not later changes to project inputs. Uploaded and typed values share the same required-field and numeric normalization rules: finite decimal numbers, at most 30 digits, bounded exponent, and 2,000 characters per value. Decimal precision remains a string. There is a 1,000-active-row limit per dataset. New valid inputs are pending, have no errors or execution attempts, and receive a new row number after the current maximum, including deleted rows. Unknown extra values cannot be saved through the service.

## Full CRUD for rows and definitions

Project input definitions have **Add**, **View**, **Edit**, and **Delete** actions. Their detail page lists workflow steps using the field. Deleting a definition requires an explicit confirmation POST and a current revision. A mapped definition is protected until its step mappings are removed/changed, with database foreign-key protection retained. Existing dataset schemas, row values, saved contexts and run snapshots are never rewritten by definition deletion. A definition change can make a saved generation context stale; review the updated project before generating/testing another version.

Dataset rows have **Add**, **View**, **Edit**, and **Delete** actions. View shows current values, validation and recent execution attempts with their recorded inputs and outputs. Delete is recoverable: it sets `deleted_at`, removes the row from active tables/counts and execution selection, and retains its data/history. **Deleted inputs** lists retained rows and offers **Restore**. Completed rows restore as completed, not pending; use duplication for intentional replay. Deleted rows cannot be edited/duplicated until restored. No dataset-row record is physically deleted.

Deletion/restoration is blocked during an active execution of that dataset or while the row is claimed/in progress. Confirmation pages use revisions to reject stale submissions. Only POST with CSRF performs mutations; GET is read-only. All routes are scoped to the project and dataset. Queue creation and delete/restore transactions serialize on the dataset before checking active runs/rows, and row claims independently reject deleted rows. Queue totals and validation ignore deleted rows; historical business-completion totals still include completed work.

Restoring an invalid input makes its dataset a preview until corrected and confirmed. Deleting the last active input also leaves a preview. Restoring cannot exceed the active-row cap. Original row numbers are retained and never reused while their deleted records remain.

Preview datasets remain previews after edits; fixing invalid rows updates validation counts and enables explicit confirmation. A confirmed dataset remains ready when valid pending inputs are added or edited. Empty previews cannot be confirmed. Counts are recomputed transactionally. Existing uploaded files are still not retained.

## Edit and execution consistency

Edit/duplicate forms include an optimistic revision of the source row. If another tab changes it or a worker claims it before saving, the old form cannot overwrite it; reload to review current data. Row numbering, state checks, edits and count updates happen in a short transaction, with write ownership acquired before reads for SQLite.

The runner loads pending rows before processing. When claiming each row, it now refreshes that row's values from the database and updates the selected `InputRow` object before robot processing begins. A saved edit before claim therefore affects execution; an edit after claim is rejected. Appended rows wait for the next run if the current run already selected its rows. This does not expand a running test's row limit or replay completed rows.

Each new `RowAttempt.input_snapshot` captures the exact claimed input values. Result tables use that snapshot, so editing a failed/pending input for another attempt never rewrites previous results. Historical attempts created before this feature have no recorded input snapshot and display **Not recorded** rather than incorrectly presenting current mutable values as original inputs. Their rows, outcomes, outputs and timing history remain stored. No speculative backfill is performed.

Queue transitions acquire write ownership before reads so row claims/completion cannot lose a race to manual dataset changes or heartbeat writes. Snapshots and row claims are committed together, before any browser action for the row. No long browser operation happens inside these transactions.

## Verification

`python manage.py test projects.test_manual_inputs projects.test_input_crud projects.test_datasets execution.test_catalog` covers manual creation, validation, saved schemas, edits, stale forms, preview correction, locks, duplication, active-row caps, CSRF/scoping, detail pages, recoverable deletion/restoration, queue exclusion, history retention and protected definition deletion. It also simulates a pending edit after queue selection and verifies that the worker processes the fresh value while later edits leave the previous attempt and result table unchanged. Tests make no paid API requests.
