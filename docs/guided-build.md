# Guided robot creation

The Build page follows **Describe → Review plan → Generate**. Preparing, editing and confirming a plan are local operations. No API call or execution occurs on page load, local preparation, save or confirmation. Paid help and paid generation have separate explicit buttons. Existing versions, request ledgers and review history are retained.

## Describe

Saved brief, ordered steps, input definitions/mappings and captured targets are reused. Local preflight checks show missing supported actions, applications, captures, output names and input mappings beside links to the affected steps. Missing technical requirements block preparation/paid review before a provider request is queued. No dataset row values or actual credentials are included in the context.

Explain semantic roles and changing labels in capture descriptions or step instructions. For example, RPA Challenge's captured Start control becomes the round indicator; saying which existing captured ID serves that role avoids making the model infer an uncaptured target. A selector's syntax alone does not establish its business meaning. If context lacks that fact, a targeted clarification is preferable to invented selectors.

**Prepare my plan** creates an unconfirmed immutable context snapshot. Mapped Fill/Select steps are suggested as per-record work; other timings remain unchosen. Both failure policies are suggested as Stop. Suggestions are visible defaults, not accepted business decisions. Local preparation does not require a configured API key.

## Review plan

Each step has one timing choice: once before records, for each record, or final verification afterward. Fill/Select cannot be assigned outside per-record execution, and saved extraction steps cannot run during setup. Backend validation still checks exact single allocation, targets, mappings, output names and recovery requirements. Old clients using the existing allocation fields remain supported.

The saved plan displays action/target/input/output relationships separately. Click Submit has no input value and does not become a dataset record. Success evidence, failure rules and assumptions remain visible for review. The editor collapses after a valid local save. Continuing after failure reveals the recovery field; server validation also works without JavaScript.

Optional Muse help is limited to three paid rounds per session. Recorded answers (including resolved questions), last locally saved decisions, outstanding questions, local missing requirements and two recent exchanges are sent. The policy asks for a short proposed plan, questions only about execution-relevant gaps, and why an answer is needed. Deterministically identical repeated questions are not added again under new IDs; this does not claim semantic deduplication or automatic contradiction detection.

Clarification keeps the complete framework contract and saved brief/steps/mappings, but omits the source example and capture diagnostics, raw locators and selector alternatives. Element IDs, application, name, type, description and image labels remain. Screenshots are only included when explicitly requested by the review path; follow-up help defaults to no screenshots. Full confirmed context and the source example are still supplied for generation. Savings depend on the project and image usage; smaller text bytes are not a guaranteed token-cost percentage.

At the review limit, local editing remains available. Users can explicitly resolve questions and replace capability warnings with supported actions. Saving their own decisions rejects pending proposals rather than silently applying them. Applying Muse proposals is a separate explicit action. Local validation and static source checks still apply.

## Generate

The page lists concrete blockers, including missing plan fields, unresolved questions/proposals, stale context, confirmation, active requests, configuration or spending limits. Saving clears prior confirmation; confirming freezes the current specification. Paid generation is enabled only after that review path is complete. Draft code is never automatically launched. Generation instructions explicitly preserve a confirmed changed-round-OR-completion condition after Submit instead of requiring the form to remain visible on its final round. Static checks do not prove complete business correctness.

Conversation history, source hashes, contract details, prior attempts and usage links stay available in collapsed details. Existing sessions can be copied onto current context with **Update specification**. This does not change old versions or their historical outcomes.

## Verification

`python manage.py test muse_builder.test_guided_build` covers the free prepare/save/confirm path, local blockers, strict phase validation, compact context, retained resolved answers, duplicate questions and the review-limit escape path. With `RUN_BROWSER_TESTS=1`, `muse_builder.test_guided_browser` verifies normal form submission, recovery visibility, confirmation/generation readiness and desktop/mobile layout on a synthetic local project without API calls. Real provider generation is a separate explicitly authorized acceptance test.
