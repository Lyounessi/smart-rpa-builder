"""Version 1 locator contract shared by inspection and the future runner."""
from urllib.parse import urlsplit, urlunsplit


def safe_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        return ""
    # Never persist credentials, queries or fragments from the browser URL.
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    try:
        if parsed.port:
            host += f":{parsed.port}"
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))[:2048]


def resolve(page, definition):
    strategy = definition["strategy"]
    if strategy == "role":
        return page.get_by_role(definition["role"], name=definition["name"], exact=True)
    if strategy == "label":
        return page.get_by_label(definition["value"], exact=True)
    if strategy == "test_id":
        return page.get_by_test_id(definition["value"])
    if strategy == "text":
        return page.get_by_text(definition["value"], exact=True)
    if strategy == "css":
        return page.locator(definition["value"])
    raise ValueError("Unsupported locator strategy")


async def validate(page, definition, baseline=None):
    target = resolve(page, definition)
    count = await target.count()
    if count == 0:
        return {"status": "missing", "count": 0, "message": "No matching element on this page."}
    if count != 1:
        return {"status": "ambiguous", "count": count, "message": f"Selector matches {count} elements. Refine or recapture it."}
    if not await target.is_visible():
        return {"status": "hidden", "count": 1, "message": "One match exists, but it is hidden."}
    result = {"status": "unique", "count": 1, "message": "Exactly one visible match."}
    if baseline:
        from .quality import fingerprint
        metadata = await target.evaluate('(el) => window.__smartRpa.metadata(el)')
        matches = fingerprint(metadata) == baseline and any(baseline.get(key) for key in ('name', 'label'))
        result.update(identity_matches=bool(matches), observed_id=metadata.get('attributes', {}).get('id', ''),
                      document_id=await page.evaluate('() => window.__smartRpa.documentId'))
        if not matches:
            result.update(status='identity_mismatch', message='One visible match exists, but its semantic identity differs or cannot be verified. Review or recapture it.')
    return result
