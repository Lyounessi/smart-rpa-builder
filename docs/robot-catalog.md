# Robots, builds and execution history

Open **Robots** in the main navigation (`/robots/`). This is the place to inspect available robot implementations, versions, runs, treated inputs and processing KPIs. Projects remain the place to design workflows. Muse generation and the Create RPA button are not implemented by this milestone.

## Pages

- **Robots list:** robot and project names, latest build version/origin/status, last run, eligible pending inputs, and distinct rows with confirmed business completion across history.
- **Robot detail:** current queue totals, paginated build versions, run history, selected-run KPIs and paginated input/results tables.
- **Build detail:** saved source files, fingerprint, origin/status and validation information. Source is escaped and displayed as text; opening this page does not import or execute it.
- **Run progress:** existing live polling and cancellation controls, now linked back to the robot and its build version for versioned runs.

Each history entry links to its run's KPIs. Use **Progress** to follow an active run and cancel it. The catalog pages are read-only snapshots on page load; live polling remains on the progress page. Input/results tables display the stored dataset values, current queue state, total attempts for that row, the selected attempt's business result, outcome, elapsed time, failed step, safe diagnostic and separate notification results. Values and source code are HTML-escaped.

## Data model and versioning

`execution.Robot` is a stable catalog entry linked to one project. `RobotBuild` stores a numbered version, origin, status, saved source/configuration, SHA-256 fingerprint and validation report. A uniqueness constraint prevents duplicate version numbers for a robot. The UI and admin expose builds read-only; registering changed code/configuration creates a new version rather than rewriting an existing snapshot.

The local registry remains the authority for execution. The runner registers a manual snapshot when a trusted robot is launched, then stores that build on `RobotRun.build`. The snapshot contains the manual robot/registry/framework source files, application URLs, captured locator definitions and element bindings. Browser resources use the saved locator/URL configuration. Unchanged source/configuration reuses the latest version; changes create the next version. Older runs keep their original build reference.

The command still executes the installed trusted Python implementation, not arbitrary source stored in the database. Selecting a historical build in the UI does not execute it. Manual snapshots are labelled **Registered / Manual**; that label does not claim Muse generation or automated code validation. The model also reserves Muse origin and queued/building/validated/failed states for the next generation milestone. They do not imply generation is available today.

Previously recorded runs are kept with **Legacy / unknown** build versions. A data migration creates catalog entries for their projects and recovers timestamps only where existing progress events provide the relevant boundaries. It does not assign today's code to historical runs.

## KPIs and timing

| Metric | Definition |
|---|---|
| Pending inputs | Valid Pending rows in confirmed datasets belonging to the project |
| Inputs in progress | Valid In progress rows in confirmed project datasets |
| Business operations completed (queue) | Valid Done rows in confirmed project datasets |
| Directory business completions | Distinct dataset row IDs with a saved business checkpoint or an OK attempt; repeated attempts do not inflate this count |
| Attempted rows (selected run) | Persisted row attempts in that run |
| Business completions (selected run) | Attempts with `business_completed_at`, or an OK outcome for legacy compatibility |
| Completion rate | Selected-run business completions / attempted rows; no attempts displays a dash |
| OK / NOK / ERROR / Unconfirmed | Counts from that run's actual persisted attempts, separate from queue state |
| Run duration | `finished_at - started_at`; includes robot setup, processing, teardown and framework cleanup after the run-start boundary |
| Active run elapsed | Time since `started_at` while the run is active; refresh the page to update |
| Average row time | Mean `finished_at - started_at` for attempts with both timestamps; includes notification work |

The run-start boundary occurs after browser resource initialization, when the framework emits `run_started`. Setup and cleanup are included, but browser startup time is not. Run/attempt start and finish times are explicitly persisted at lifecycle boundaries. A cancelled attempt gets an interruption finish time during normal cleanup. A hard-crashed worker has no reliable end time: lease recovery does not invent one, and missing timings display **Not recorded**. Untimed attempts are excluded from the average; its sample count is displayed. No throughput or timing claims are inferred from record `updated_at` values.

Business success and notification success remain separate. A row may be **Done**, with a confirmed business operation, an **ERROR** attempt outcome and a failed or uncertain email action. Business-completion KPIs still count that operation. See [email steps and durable checkpoints](email-workflow-steps.md).

History and result queries are scoped to the selected robot's project; choosing a run from another project's robot returns 404. This is a local workspace feature, not a new multi-user authorization layer. The platform's existing authentication/access model is unchanged.

## Make an existing manual robot visible

After applying migrations, refresh registration for existing, complete fixture projects:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py sync_robot_catalog
```

The sync command registers only the trusted Invoice Checks and Invoice Checks Email examples already present in the database. It creates no projects, sends no messages and runs no robots. Projects without a built/registered robot are not presented as executable robots. If no implementations exist, the catalog shows an empty state and a link back to projects.

For a new isolated demonstration, follow the [framework demo](robot-framework.md#local-example) or [fake-email demo](email-workflow-steps.md#run-the-fake-email-example), then run the robot or sync the catalog. CLI execution automatically records the build version; no separate sync is needed before a run. Real credentials, recordings, dataset contents and actual captured screenshots are not copied into the build source snapshot.

## Verification

```powershell
.\.venv\Scripts\python.exe manage.py test execution.test_catalog
```

Tests cover KPI definitions and measured durations, business completion after notification failure, unique historical row counts, run scoping, escaped source display, pagination, version reuse/change, old-run build retention, lifecycle timestamps and event-based historical backfill. The full framework/browser regression suite remains described in the [framework guide](robot-framework.md#tests-and-limits).

Muse context assembly, generation requests, generated-code review/validation, deployment, historical-version execution, charts and result exports are deferred. The catalog/build records provide their integration point without calling Muse or running generated code.
