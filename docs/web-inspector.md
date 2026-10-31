# Web inspector

1. Create a project, a web application with its starting URL, and a step with an instruction and application selected.
2. Save the step, then choose **Capture / test target**.
3. Choose **Open inspection browser**. A separate visible Chromium browser opens; navigate or log in manually.
4. Choose **Inspect element** in Django or **Select element** in the browser toolbar. Hover to highlight, then click to capture without the ordinary click action. Escape or **Cancel selection** returns to browsing.
5. Return to Django to review the highlighted viewport and element crop. Name the element and choose **Save target to step**, or discard it. Recapturing replaces only the unsaved draft. The browser remains open during review and saving.
6. Choose **Test saved locator** to check the current page. The result distinguishes missing, ambiguous, hidden, and one visible match; a unique visible match is highlighted. Results are timestamped historical checks, not a guarantee of future validity.
7. **Stop inspector** in either interface closes Chromium and ends the worker. Manual browser closure also ends the session.

The toolbar can be moved between the top and bottom of the page if it covers a target. It is excluded from screenshots. Only one inspection browser runs at a time. Opening another step for the same project and application reuses the browser when no operation is in progress; draft captures retain their original step. Stop before switching applications or projects.

Saved targets and screenshot files survive restarting Django. Open the browser again, navigate to the relevant page, and test the saved locator. Navigation is manual; a capture URL does not automatically drive browser navigation.

### Process and persistence

Django launches `manage.py inspect_browser` as one child process. Its async Playwright loop owns the visible browser, services toolbar events, and reads fixed commands from SQLite. Django serves HTML and polls session status through HTMX every two seconds. Short database transactions keep browser operations outside database locks. Pending non-stop commands expire after 30 seconds and are not retried automatically.

The worker checks the local server's session health endpoint every two seconds. Three failed checks close the browser, including after the server process restarts. Worker heartbeats allow Django to mark stale sessions interrupted after 30 seconds. Screenshots and saved targets remain intact. Use one Django server process; automatic reloads intentionally interrupt inspection, so `--noreload` is recommended while capturing.

A selection produces a draft tied to its exact step. Saving creates a reusable element UUID and attaches it transactionally, replacing the current step reference. The previous saved element remains available for reuse. Draft recapture/discard deletes that draft's images; saved images are retained. Unsaved drafts survive a stopped session for review and occupy local media space until saved, replaced, or discarded.

### Privacy and limits

- Screenshots mask inputs, textareas, editable regions, and embedded surfaces before the image is persisted. The element crop is cut from the same masked viewport image. Input values, cookies, browser storage, full HTML, and authentication state are not exported. Browser contexts are ephemeral; log in again after reopening.
- Masking is not complete secret detection: ordinary text, labels, page paths, images, or custom controls may contain sensitive information. Review both screenshots and discard unsuitable captures. Automatically recorded capture URLs omit user information, query strings, and fragments. Never enter actual secrets into workflow instructions or target URLs.
- Selectors prefer test IDs, roles and associated labels, then allowlisted semantic attributes (including Angular field names), ID/descriptive attributes, label/parent context and then classes. An ID is not required; see [selector fallbacks and RPA Challenge](inspector-selectors.md). Version 1 definitions use `strategy` plus `role`/`name` or `value`; the resolver is in `inspector/locators.py`. No absolute XPath or positional fallback is generated. Some controls cannot produce a unique stable selector and require another selection.
- Each new capture stores `selector_quality` alongside the locator for future Muse context: an ID-pattern assessment, a semantic identity baseline, and a bounded history of successful document/session observations. Suspected generated IDs are skipped during candidate selection. Pattern checks are heuristics, not proof. Repeated tests in one document do not increase stability evidence. Successful identity checks across manual reloads or browser reopenings are labelled `observed_across_documents`; mismatches and failed tests require review. Unlabelled controls may lack enough semantic evidence to verify identity. Existing captures remain unverified until recaptured. Saved-locator tests never automatically reload or navigate. OCR remains deferred; saved selector evidence is included in Muse context.
- Only the main document of the original tab is supported. New tabs/popups are closed; iframe internals, closed shadow roots, canvas, embedded viewers, and complex custom controls are excluded. OCR and visual targeting are future possibilities, not active fallbacks.
- Click interception is best effort for ordinary HTML controls. Browser-native UI and unusual application event handlers are outside the MVP guarantee. Work on non-critical pages when capturing.
- The target browser must run in the interactive Windows host session. Docker/headless hosting, multi-user inspection, and production deployment are outside this milestone.
- Muse clarification receives a compact plan context with element identities and optional referenced screenshots; generation receives the full confirmed specification and selectors. Confirmed specifications can generate drafts, followed by explicit reviewed tests. Production activation remains deferred. No RAG or vector database is used.

### Browser checks

The standard suite runs database, review, project-boundary, ordering, and lifecycle-state tests without launching browsers. To also run real Chromium selection/masking and visible-browser start/stop/disconnect checks:

```powershell
$env:RUN_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe manage.py test
Remove-Item Env:RUN_BROWSER_TESTS
```
