# Documentation

Start with the [project overview, local installation and API key setup](../README.md).

## Create an automation

- [Projects and workflow steps](workflow-editor.md): automation brief, target applications, actions and input mappings.
- [Web inspector](web-inspector.md): capture, save and test interface elements; browser lifecycle and limits.
- [Selector quality](inspector-selectors.md): candidate priority, XPath, changing IDs and identity evidence.
- [Input datasets](datasets.md): CSV/XLSX formats, headers, validation and confirmation.
- [Manual inputs](manual-inputs.md): create/edit records, input definitions and history preservation.
- [Guided Build flow](guided-build.md): Describe → Review plan → Generate, optional Muse help and local validation.

## Run and inspect results

- [Draft testing](draft-testing.md): source review, Run controls, CLI and local demo.
- [Project results](project-results.md): pending versus treated records and treatment-date filters.
- [Technical logs](execution-logs.md): action timings, readable failures and JSONL download.
- [Robot catalog](robot-catalog.md): versions, run history and timing KPIs.
- [Workflow outputs](workflow-outputs.md): per-record extraction and stored results.
- [Final verification](final-verification.md): once-only final checks and run-level outputs.

## Configuration and framework development

- [Muse API integration](muse-integration.md): environment configuration, connection check and errors.
- [Context and spending controls](muse-context-budget.md): immutable snapshots, limits and request accounting.
- [Clarification internals](muse-conversation.md): proposals, bounded conversations and worker recovery. For the current user interface, start with the Guided Build flow above.
- [Draft generation](muse-generation.md): source validation, repair attempts and recovery.
- [Python robot framework](robot-framework.md): lifecycle, public API, manual robots and examples.
- [Email extension](email-workflow-steps.md): injected adapter and fake-only demonstration.
- [Development setup](development.md): dependency files, admin, storage and local checks.

## Keeping the documentation manageable

Keep the root README focused on what the project does, installation, API-key setup and first use. Put detailed instructions in the relevant feature guide, and link new guides here. Update existing guides when behavior changes instead of appending milestone reports to the README. Local databases, API keys, captures and generated test artifacts do not belong in documentation commits.
