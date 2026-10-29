# Inspector selector fallbacks

An ID is not required to capture an element. Selection tries a bounded list of candidates in order and accepts a candidate only if it resolves to exactly one visible element and that element is the clicked target. It never chooses the first match of an ambiguous selector.

1. Test ID.
2. Role with accessible name, then associated label.
3. Allowlisted semantic attributes: `formcontrolname`, `ng-reflect-name`, dedicated test/automation attributes, ARIA label and name.
4. ID without a suspected generated pattern (still unverified).
5. Placeholder, title, alt and supported exact text.
6. Class token and bounded class-pair combinations, excluding common state/generated patterns.
7. Up to three parent levels using semantic attributes, a label associated by single-control container structure, or class context.

At most 48 deduplicated candidates are considered. CSS strings escape quotes, backslashes and control characters without losing Unicode. Unsupported candidate syntax is skipped; a closed page still stops capture. If all candidates fail, the message explains the supported fallbacks. Absolute/positional XPath, coordinate fallback, OCR, frames and closed shadow DOM are not added by this change.

Metadata collection uses a fixed attribute allowlist. It does not collect typed field values, `ng-reflect-model`, arbitrary `data-*`, HTML or parent body text. Only bounded class tokens and nearby label text from a container with exactly one control are collected. Input elements of type button/submit/reset can use their visible `value` caption as a button name; text/password/other data values remain excluded. Existing screenshot masking is retained.

## RPA Challenge

RPA Challenge exposes semantic field names while IDs/names change. Examples include:

```css
input[ng-reflect-name="labelFirstName"]
input[ng-reflect-name="labelLastName"]
input[ng-reflect-name="labelCompanyName"]
input[ng-reflect-name="labelRole"]
input[ng-reflect-name="labelAddress"]
input[ng-reflect-name="labelEmail"]
input[ng-reflect-name="labelPhone"]
```

These are candidates to validate, not a promise that the website will never change. The live check captured all seven fields and verified unique matches and identity evidence after reload despite all seven IDs changing. Separate live checks captured Start using unique class CSS and Submit using its button role/caption. The checks did not start the challenge, submit data or create database captures.

## Saved targets and identity evidence

The locator contract remains version 1: existing CSS/role/label/test-ID/text resolution works in both inspector and runner. No migration is required. Capture review names can use nearby labels when no associated accessible name exists.

New identity baselines can include nearby labels and allowlisted semantic attributes. Old baselines compare only their recorded fields, so adding these metadata fields does not invalidate old named captures. Unique class-only matches without semantic identity stay **unverified**, rather than being incorrectly called an identity mismatch. Real recorded-identity differences still require review. Cross-document observations remain evidence, never a stability guarantee.

Stop/reopen an existing inspector to load the updated selection script. Recapture failing targets; old saved selectors are not rewritten automatically. The normal save flow persists new metadata, screenshots and selectors. A locator still needs manual testing after page changes and across the workflow.

## Verification

`python manage.py test inspector.test_candidates inspector.test_quality` checks ordering, escaping, bounded candidates and evidence handling. With `RUN_BROWSER_TESTS=1`, `inspector.test_candidates.SelectorFallbackBrowserTests` exercises the full capture pipeline on local RPA-like HTML, changing IDs/positions, class combinations, parent and nearby-label selectors, button captions, ambiguity rejection and exclusion of entered values. Live-site checks are separate and are not run automatically by the regression suite.
