# Create a project and its robot

Start the app using the [local installation instructions](../README.md). Configure `MUSE_APIKEY` in your local `.env` and restart Django before generation. Preparing a plan does not call the API; Muse help and generation do.

## 1. Describe the project

To put an old project away, open it, expand **Project actions**, and choose **Archive project and robot**. Both disappear from active lists; inputs, robot versions, results and recordings stay intact. Open **Archived projects** on the workspace to view and restore them. Finish or stop an active run before archiving. Restore an archived project before launching another run.

Choose **Create project**, enter a name and description, and select Web application. Desktop automation is reserved for later. Add an **Automation brief** with the goal, global rules and success criteria when useful.

Add a **Target application** with its starting URL. Each captured element also retains the URL where it was captured.

The project page groups field definitions and datasets under **Input data**, with **Workflow steps** at the bottom. A single **Next action** card links to missing setup, active progress, generation or the latest results. It is a navigation suggestion; generation and execution still perform their own validation. **Project actions** contains editing, build, history and archive links.

## 2. Define inputs and load records

Add the input columns the robot needs, such as `first_name` and `email`. Choose their type and whether they are required. Buttons such as Submit are workflow actions, not input columns.

Upload CSV/XLSX with matching column headers, or create a dataset manually and add records. Review validation errors and confirm the dataset. Only valid pending records are eligible for execution. See [dataset rules](datasets.md).

## 3. Add steps and capture targets

Create ordered steps with one action each. Select the target application, use **Capture / test target**, choose the element in the inspector, and save the capture. Test the target after reloading the page when practical. Stop the inspector when finished.

For **Fill** and **Select option**, map the corresponding input column. **Click** needs a target but no input mapping. **Read text** needs a target and an output name. Explain what proves the action succeeded, including targets whose meaning changes after a click.

## 4. Prepare and confirm the plan

Open **Build with Muse** and prepare the plan locally. Assign every step:

- **Before processing:** runs once, such as navigating and clicking Start.
- **For each record:** fills mapped fields and submits one record.
- **After processing:** verifies the final result after all selected records succeed.

State observable success evidence and rejection handling. For RPA Challenge: read the round indicator before Submit; confirm that the round changes **or** Congratulations appears. Do not require the form to remain visible after the final submission. Save Congratulations as the final output. Stop on uncertain submission; do not automatically resubmit.

Save the plan, inspect its summary, and confirm the agreed specification. Optional Muse help can clarify unresolved decisions but uses paid API requests. Changes to the project may require refreshing and confirming a new plan.

## 5. Generate and review

Choose **Generate draft robot**. This sends the saved project context, referenced captures and framework contract to Muse; dataset record values and credentials are excluded. Follow the result or any clarification message before retrying. An interrupted request can leave uncertain charges reserved.

Open the saved version and review its code. Static checks do not prove business correctness. Generation does not execute or activate the robot.

## 6. Run the robot

Choose **Run robot**, select the version and confirmed dataset, and set the maximum pending records (up to 50). For a challenge that finishes after 10 records, select all 10; a partial run may not reach its final verification screen.

Optionally enable **Record browser page video**. Review and acknowledge the exact source version, then launch. The robot runs locally. Use the progress page to follow actions or request a stop between bounded actions.

## 7. Check results and recordings

Review status, duration, confirmed treatments, remaining selected records, final outputs and errors on the run page. In the robot history, open **View KPIs** for original inputs, row outcomes, timing and outputs. Project **Results** provides treatment dates and filters.

Use **Watch recording** to play a saved browser recording, or download its WebM file. Recordings are optional, become available after browser cleanup, and remain under local `media/runs/<run-id>/`. They may contain entered values. Missing or moved recordings are shown as unavailable.

Confirmed business operations move out of pending inputs into treated results. A failed check after Submit does not prove the external submission failed: inspect the target application and technical logs before retrying. Notification failures do not undo a confirmed business operation.
