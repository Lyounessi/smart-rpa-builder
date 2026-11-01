# Projects and workflow steps

A project represents an automation workflow. It stores its name, description, application setup, optional automation brief, input definitions, target applications and ordered steps. The current MVP supports web applications; desktop is reserved for later. Multiple-application projects still use web targets only.

## Automation brief

Use **Add/Edit automation brief** on the project page, or the project creation/edit form:

- **Goal:** what the automation should accomplish.
- **Global rules:** constraints applying across the workflow.
- **Success criteria:** what successful processing means.

All three fields are optional and support up to 5,000 characters each. Existing projects can leave them empty. Keep credentials out of descriptions and instructions. The brief supplements steps; it does not silently replace their targets, input mappings or execution settings. Identified contradictions need clarification; automatic detection is not guaranteed.

## Target applications

Each target application has a name and HTTP(S) starting URL. Embedded URL credentials are rejected. Starting URLs describe where to launch; saved captures retain their own capture URL. A capture URL does not itself create navigation logic. Use step instructions to describe intended navigation.

## Step actions and mappings

Save a short instruction for each step and choose its action:

| Action | Required data |
|---|---|
| Click | Captured target; no input value |
| Fill | Captured target and existing input field |
| Select option | Captured target and existing input field |
| Read text → save output | Captured target and output name |

Fill/Select mappings reference input definitions in the same project. Click clears the input mapping. Captured target choices are restricted to the selected application and project. Draft steps can be incomplete while editing, but the Build flow blocks missing targets, actions or mappings before a paid review. Input definitions used by mapped steps are protected from deletion.

Use Capture / test target after saving a step with its web application. Saved elements have reusable UUIDs, structured locators, capture metadata and screenshot references. The current editor attaches zero or one captured target per step; an explicit reference model preserves reuse. The inspector and source snapshots keep historical evidence separately.

Reorder steps using the up/down controls. Reordering uses transactional swaps with unique positions per project. Project/step deletion and simultaneous multi-user editing are outside the MVP scope. Data persists in SQLite; captures persist under `media/`.

## Continue building

- [Web inspector](web-inspector.md): capture and test targets.
- [Input datasets](datasets.md) and [manual input management](manual-inputs.md).
- [Guided Build flow](guided-build.md): assign steps before processing, per record or to final verification; define success evidence and failure rules; confirm before generation.
- [Outputs](workflow-outputs.md) and [final verification](final-verification.md).
