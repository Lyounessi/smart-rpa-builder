# User guide: create a project and its robot

Start the app using the [local installation instructions](../README.md). Configure `MUSE_APIKEY` in your local `.env` and restart Django before generation. Preparing a plan does not call the API; Muse help and generation do.

## Before you begin

You need a running local app, a supported website, and some records to process. A Muse API key is needed only for paid clarification and generation. Use the [installation and API-key instructions](../README.md) if you have not started the app yet.

A **project** holds the instructions, target website, captures and data definitions. A **dataset** holds records to process. A **robot version** is saved Python code generated for a confirmed plan. A **run** executes one reviewed version against pending records and keeps its own results.

Follow the numbered sections below. You can revisit earlier sections at any time. The **Next action** card suggests where to continue; it does not start generation or execution automatically.

## 1. Describe the project

Choose **Create project**, enter a name and description, and select Web application. Desktop automation is reserved for later. Add an **Automation brief** with the goal, global rules and success criteria when useful.

Under **Target applications**, choose **Add target application**, give the website a recognizable name, and enter its starting URL, for example `https://rpachallenge.com/`. Save the application. Each captured element also retains the URL where it was captured.

Example brief:

- **Goal:** enter one spreadsheet record into the challenge form for each round.
- **Global rules:** field positions change after every submission; identify fields by their saved selectors.
- **Success criteria:** each submission advances the round or shows completion; save the final Congratulations message.

Keep the brief consistent with the explicit workflow steps and input mappings. If Muse identifies conflicting instructions, clarify them before generating.

The project page groups field definitions and datasets under **Input data**, with **Workflow steps** at the bottom. A single **Next action** card links to missing setup, active progress, generation or the latest results. It is a navigation suggestion; generation and execution still perform their own validation. **Project actions** contains editing, build, history and archive links.

## 2. Define inputs and load records

Add the input columns the robot needs, such as `first_name` and `email`. Choose their type and whether they are required. Buttons such as Submit are workflow actions, not input columns.

For a challenge project, define these seven Text inputs: `first_name`, `last_name`, `company_name`, `role_in_company`, `address`, `email`, and `phone_number`. Text is useful for phone numbers because leading zeros must be preserved.

Choose **Upload input file** to upload CSV/XLSX, or **Create dataset manually** to enter records in the app. File headers must match the defined keys exactly, including optional columns; unexpected columns are rejected. Example CSV for a simple two-field project:

```csv
first_name,email
Alice,alice@example.invalid
Bob,bob@example.invalid
```

This example requires a project with exactly those two input definitions. For the seven-field challenge, provide all seven headers and the official ten challenge records.

Use **Add input** inside a manual dataset to enter a record. Open a pending record to edit it; record actions also allow viewing, deletion and duplication where available. Completed records remain in history. Restore a deleted record through the dataset’s deleted-record view.

Review validation errors, then choose **Confirm dataset** once all records are valid. Only valid pending records are eligible for execution. See [dataset rules](datasets.md).

## 3. Add steps and capture targets

Scroll to **Workflow steps** at the bottom of the project and choose **Add step**. Give the step a clear name, describe one action, and select its target application. Save the step before capturing its target.

For each interface target:

1. Choose **Capture / test target** on the saved step.
2. Choose **Open inspection browser**. Navigate or sign in manually if needed.
3. Choose **Inspect element** in the app or **Select element** in the browser toolbar.
4. Hover over the intended element and click to capture it. In selection mode, this captures the element instead of performing its normal action. Exit selection mode when you need to navigate normally.
5. Return to the app, review the highlighted screenshot, name the target clearly, and choose **Save target to step**.
6. Choose **Test saved locator**. Look for one visible match. A missing, hidden or ambiguous match needs review; a successful test is evidence, not a guarantee.
7. Reload or reopen the page manually and test again when practical. Choose **Stop inspector** when finished; it closes the inspection browser.

If later steps are on another page, navigate there in the inspection browser before capturing. Write the required navigation and action order in the workflow instructions; saving a capture URL alone does not make the robot navigate there.

For **Fill** and **Select option**, map the corresponding input column. **Click** needs a target but no input mapping. **Read text** needs a target and an output name. Explain what proves the action succeeded, including targets whose meaning changes after a click.

Example challenge workflow:

| Order | Step | Action | Input mapping / output |
| --- | --- | --- | --- |
| 1 | Start challenge | Click | No input mapping |
| 2–8 | Seven form fields | Fill | One matching input key per field |
| 9 | Submit record | Click | No input mapping |
| 10 | Read completion message | Read text | Output: `congratulations` |

Give Submit an instruction such as “Submit this record once, then wait for the round to advance or the completion message to appear.” Explain that the same Start button becomes the round indicator. A completed click alone is not proof that the record was accepted.

## 4. Prepare and confirm the plan

Open **Project actions → Build with Muse**, then choose **Prepare my plan (no API call)**. If the button is disabled, follow the listed missing-step or target links before continuing. Assign every step:

- **Before processing:** runs once, such as navigating and clicking Start.
- **For each record:** fills mapped fields and submits one record.
- **After processing:** verifies the final result after all selected records succeed.

State observable success evidence and rejection handling. For RPA Challenge: read the round indicator before Submit; confirm that the round changes **or** Congratulations appears. Do not require the form to remain visible after the final submission. Save Congratulations as the final output. Stop on uncertain submission; do not automatically resubmit.

Choose **Save plan (no API call)**, inspect the saved summary, then choose **Confirm agreed specification**. Saving further changes clears confirmation; confirm the revised summary again. Optional Muse help can clarify unresolved decisions but uses paid API requests. Changes to the project may require refreshing and confirming a new plan.

## 5. Generate and review

Choose **Generate draft robot**. This sends the saved project context, referenced captures and framework contract to Muse; dataset record values and credentials are excluded. Follow the result or any clarification message before retrying. An interrupted request can leave uncertain charges reserved.

When generation finishes, choose **Open robot versions and runs**, then open the new version and review its code. Robot names are derived from project names, for example `Invoice Checks` becomes `ROBOT_INVOICE_CHECKS`. Static checks do not prove business correctness. Generation does not execute or activate the robot.

## 6. Run the robot

Choose **Run robot**, select the version and confirmed dataset, and set the maximum pending records (up to 50). For a challenge that finishes after 10 records, select all 10; a partial run may not reach its final verification screen.

Check that the selected dataset belongs to this project and matches the version’s input definitions. Only valid pending records are selected; treated and deleted records are excluded.

Optionally enable **Record browser page video**. Review and acknowledge the exact source version, then launch. The robot runs locally. Use the progress page to follow actions or request a stop between bounded actions.

## 7. Check results and recordings

Review status, duration, confirmed treatments, remaining selected records, final outputs and errors on the run page. In the robot history, open **View KPIs** for original inputs, row outcomes, timing and outputs. Project **Results** provides treatment dates and filters.

Use **Watch recording** to play a saved browser recording, or download its WebM file. Recordings are optional, become available after browser cleanup, and remain under local `media/runs/<run-id>/`. They may contain entered values. Missing or moved recordings are shown as unavailable.

Confirmed business operations move out of pending inputs into treated results. A failed check after Submit does not prove the external submission failed: inspect the target application and technical logs before retrying. Notification failures do not undo a confirmed business operation.

## 8. Change the workflow or test again

- Edit input definitions, instructions or captures from the project. Existing robot versions retain their saved context; if a version is stale, prepare and confirm the updated plan and generate a new draft.
- To repeat a completed challenge, create a fresh dataset or duplicate records deliberately. Completed rows are not automatically reset to Pending.
- A stopped or failed run may leave uncertain external effects. Check the target application before retrying pending records.
- Archive old projects through **Project actions → Archive project and robot**. Restore them through **Archived projects** on the workspace. Archiving preserves robot versions, inputs, history and recordings, and blocks new runs until restored.

## Common questions and blockers

| What you see | What to do |
| --- | --- |
| Cannot prepare the plan | Complete the listed action, application, capture, input mapping or output name. |
| Generate button disabled | Assign every step a phase, fill success/rejection rules, save, confirm, and review any configuration or spending blocker. |
| Muse asks a question | Answer the specific unresolved decision. You can save supported structured decisions locally rather than requiring another paid discussion round. |
| Generation stopped unexpectedly | Review the operation and usage information. Unknown charges can remain reserved; do not repeatedly click Generate expecting a free retry. |
| No dataset available to run | Confirm a valid dataset with pending records and matching input definitions. Restore the project if it is archived. |
| Last record fails after Submit | Check whether the final screen replaced the form. Success evidence must allow completion as an alternative to another round. |
| No Watch recording option | Recording must be enabled before launch and finalized at browser cleanup. Files moved or removed from the machine cannot be played. |
| Need the exact failing action | Open the run’s technical logs or download JSONL. Check the failed step, target, exception type and code location. |
| Changes do not appear | Restart Django and workers after code/configuration updates; retain `--noreload` during inspection. |

## Ready-to-run checklist

- Target website and all required steps are saved.
- Each Fill/Select action maps to the intended input column.
- Captured targets were reviewed and tested.
- Dataset is valid, confirmed, and contains the intended pending records.
- Setup, per-record work and final checks are assigned explicitly.
- Success evidence and failure handling are clear; the plan is saved and confirmed.
- Generated source was reviewed, and the selected record limit can reach the final state.
- Recording is enabled if you want execution evidence.

For more detail, see [inspection](web-inspector.md), [datasets](datasets.md), [guided planning](guided-build.md), [execution](draft-testing.md), and [results](project-results.md).
