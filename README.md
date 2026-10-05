# scraper

Discover source pages using synchronous Playwright:

```bash
uv sync --locked
uv run playwright install --with-deps chromium
uv run python traverse.py
uv run python traverse.py --index "Melbourne Water"
```

`traverse.py` keeps the local `(name, url)` index tuples in `INDEXES`. Previously
blocked indexes are listed separately in `BLOCKED_INDEXES`; past projects are
explicitly skipped. Edit these lists locally as needed.

Traversal discovers open/upcoming consultations and current project candidates.
News, bills, and uncertain project candidates still need eligibility and relevance
checks downstream. Results are kept in memory and printed; there is no database,
checkpoint, or scheduled workflow yet. A failed index is reported separately from
an empty listing; the remaining indexes continue and the process exits nonzero.

Use the existing helpers after discovery:

```python
from playwright.sync_api import sync_playwright
from helpers import process_single_source
from traverse import traverse_index

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        sources = traverse_index(
            "Melbourne Water", "https://letstalk.melbournewater.com.au/projects", browser
        )
        for source in sources:
            text = process_single_source(source, browser)
    finally:
        browser.close()
```