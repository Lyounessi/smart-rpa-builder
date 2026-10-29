# Phase 5: explicit tests of reviewed robot drafts

Open **Robots → robot → version**, expand the saved source, and review it. The **Test this draft version** section lets you select a confirmed dataset from the same project, choose 1–5 pending rows (default 2), optionally record browser-page video, and acknowledge the exact source version before running it.

A test is real execution: it can act on its configured web application and updates the selected dataset's row outcomes. Use fictional data and a test application first. Generated Python runs with the local worker's ordinary permissions. Static validation is not a sandbox or isolation boundary; only execute code you have reviewed and trust. Email uses the injected fake adapter and cannot send real provider messages through that adapter. This does not constrain arbitrary trusted Python code's permissions.

## Preconditions and immutable version binding

The POST requires CSRF, explicit acknowledgement, the saved source digest, a valid ready dataset with pending rows, and no other active robot run. Cross-project datasets are rejected. Source/specification fingerprints, current project/capture/contract context and static compatibility are rechecked both before queuing and before importing source. Missing inputs, modified source, stale context and invalid limits fail before browser actions. Viewing a source/build or refreshing progress never imports source or starts a run.

Each test saves `is_test`, its exact `RobotBuild`, reviewed source digest, review timestamp and test options on `RobotRun`. The test does not activate/register the generated version in the manual registry or change its draft status. Existing manual `run_robot` commands remain available and unchanged.

One hidden local worker claims the queued test. A duplicate command cannot import code or replay actions. The worker loads the explicitly reviewed class into an in-memory registry and injects frozen application URLs and captured selectors, existing environment secret references, cancellation, queue/events, and fake email. Browser resources are opened/closed by the framework. No pip, Muse generation or provider authentication occurs during execution.

Configured stop/recovery decisions come from the frozen specification. The framework limits queue selection to the requested pending row count. Successful rows become done; failed rows return to pending unless business completion was durably checkpointed. Tests do not reset completed rows or automatically retry them. Use a fresh dataset for another clean two-row demo. Cooperative cancellation, active-run exclusion and lease recovery retain existing behavior.

## Results

Follow live progress and cancellation at `/execution/<run-id>/`. The version page lists recent tests. Its **Outputs and timing KPIs** link opens the selected run in the Robots catalog, showing row outcomes, saved outputs, duration, average row time and business/notification completion. Test runs are labelled in history. Optional recordings may contain sensitive content and stay under local `media/runs/`.

## CLI

After reviewing a build's source, copy its displayed fingerprint:

```powershell
python manage.py test_robot_build BUILD_ID --dataset DATASET_ID --reviewed-source-digest SOURCE_DIGEST --row-limit 2
```

`--record-screen` optionally records browser-page video. `execute_robot_test RUN_UUID` is the worker entry point for an already queued, explicitly reviewed run; it cannot queue a new test or rerun a completed one.

## Local greeting demo

```powershell
python manage.py serve_draft_fixture --port 8766
```

In another terminal:

```powershell
python manage.py prepare_draft_demo --port 8766
```

This creates **Greeting draft demo**, a local target application, three captured CSS targets, fill/click/read-text steps, a confirmed specification and two fictional inputs (`Alice`, `Bob`). It makes no API call and creates no executable build. Generate a draft from its Build with Muse page, review it, then test it. Expected outputs are `Hello, Alice!` and `Hello, Bob!`. The command refuses to overwrite an existing demo.

After completing both inputs, upload [greeting-demo.csv](fixtures/greeting-demo.csv) as a new dataset to repeat the test. Completed rows in the original dataset stay done.

For offline regression testing, `prepare_draft_demo --port 8766 --local-robot` also creates an explicitly **manual** draft fixture. It is never labelled as Muse-generated. The fictional playground has no account, provider integration or external service dependency.

## Verification

`python manage.py test execution.test_draft_tests` covers source acknowledgement/fingerprints, POST/CSRF, project scoping, stale context, row limits, duplicate workers, cancellation, launch failure, saved outputs and retained draft status using a fake browser. With `RUN_BROWSER_TESTS=1`, `execution.test_draft_tests.DraftBrowserTests` runs the two-row fixture in real Chromium and checks persisted outputs and results. Automated regression tests make no paid Muse requests.
