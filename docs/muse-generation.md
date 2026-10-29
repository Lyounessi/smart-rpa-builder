# Muse draft generation (Phase 4)

Open a project's **Build with Muse** page (`/projects/<id>/build/`). Review the workflow, resolve questions and proposals, and confirm the agreed specification. **Generate draft robot** is a separate, explicit paid POST action. Viewing or refreshing any page sends no API request.

## Fixed generation context

Each generation job freezes the confirmed specification, snapshot and hash. It includes the automation brief, ordered instructions, setup/per-row decisions, input definitions and mappings, referenced targets/selectors, relevant highlighted screenshots, framework contract and example. Platform instructions remain separate from user-authored data. Dataset row values and actual credentials are excluded. Known configured secret values are rejected in responses before persistence; this is not a guarantee that all sensitive content can be detected. Review captures before submitting.

The initial request includes snapshot images. Repair requests reuse the fixed text context and previous attempt/diagnostics, omitting images to reduce cost. Each is independently accounted through the existing spending ledger and conservative reservation rules. `MUSE_GENERATION_OUTPUT_TOKENS` defaults to 4096 (1024–16384, also bounded by `MUSE_MAX_OUTPUT_TOKENS`). There is no automatic dependency installation or provider/network retry.

Muse returns strict JSON with `source_code`, `assumptions` and `clarification_questions`. Source names follow the project, for example `ROBOT_INVOICE_CHECKS.py` with class `ROBOT_INVOICE_CHECKS`. Questions stop generation and return the session to clarification, clearing confirmation. A fresh confirmation is required. Generation does not consume clarification rounds; the existing three-round clarification cap still applies, with local specification editing available afterward.

## Static checks and repairs

The validator parses source with Python AST; it never imports or executes it. Checks include a bounded source/AST size, exact class/BaseRobot inheritance, supported imports and lifecycle signatures, public context operations, fixed known element/application IDs and input keys, mapped inputs and configured lifecycle placement, named progress steps, a visible success assertion and verified recovery when continuation is configured. Arbitrary module statements, resource ownership overrides, dynamic imports and unsupported calls are rejected.

These are conservative compatibility checks, not a Python sandbox, full control-flow proof or proof of business correctness/safety. In particular, a visible element alone does not prove that the user's success criteria have been fulfilled. Human review and explicit testing remain necessary.

An invalid structured response or static-check failure permits at most **two repair requests**, so each job makes at most three requests. Each attempt is saved with diagnostics. A provider failure, timeout, stale specification or exhausted budget stops the job without an automatic network retry. Partial/uncertain usage retains its reservation. A project, capture, contract or confirmed-specification change before/during generation rejects the result. No prior version is overwritten.

After response/schema and known-secret checks, the paid response is saved before static validation and draft creation. A local processing failure keeps it available in attempt history, reports its stage and exception type, and marks the request as a local failure while preserving settled usage. Logs contain job IDs/stages/types rather than exception messages or source. SQLite draft transactions acquire write ownership before reads to avoid a heartbeat-induced read-to-write lock upgrade. Earlier failed jobs with no saved response cannot reconstruct that source locally.

## Draft storage and execution boundary

Successful output creates a new `execution.RobotBuild` with `origin=muse`, `is_draft=True`, `status=validated` (static checks only), source text/digest, frozen specification/hash, contract version/hash, assumptions and report. The job links to this version. Find it from the build page or `/robots/` → robot → version. Sources, assumptions and diagnostics are rendered as escaped text.

Generation never activates the build, registers a generated class, creates a RobotRun, imports source, opens a browser, or sends email. The existing CLI continues to use the trusted manual registry. Explicit testing/activation belongs to Phase 5.

Existing projects/builds remain valid through additive migrations. `GenerationJob` groups one initial generation and up to two repairs; existing `BuildOperation` records now distinguish clarification/generation/repair and retain response data and validation errors. `MuseRequest` links to each individual attempt, preserving usage accounting. Django admin exposes job and attempt records read-only.

## Worker and recovery

HTTP queues one job and launches `python manage.py generate_muse_robot <job-uuid>` in a hidden local worker. Only that worker can claim the initial queued operation; replaying the command does not restart requests. Repairs remain with the original worker. The UI polls while the operation is active and displays its heartbeat/attempt ID.

After verifying/stopping an abandoned worker, use:

```powershell
python manage.py close_abandoned_build_review <active-operation-uuid> --worker-stopped
```

This closes the generation and releases the local execution slot while retaining uncertain API charges. It does not cancel provider work. Never run recovery while its worker is still processing.

## Verification

`python manage.py test muse_builder.test_generation` uses fake responses/adapters only. It covers successful versioned drafts, duplicate workers, maximum repairs, invalid structured responses, questions, stale context before/during responses, provider/budget failure, secret rejection, static incompatibilities, recovery, escaped history, POST/CSRF/project scoping and real budget-service accounting with a mocked provider. No test sends a live Muse request or executes generated source.
