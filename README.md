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

Collect listings, extract HTML/PDF text, and ask Claude for structured opportunity
metadata using Pydantic. Copy `.env.example` to `.env` and fill in:

```dotenv
ANTHROPIC_API_KEY=your-api-key
CLAUDE_MODEL=claude-sonnet-4-6
```

`python-dotenv` loads `.env` beside `composer.py`, regardless of the working
directory. Existing environment variables take precedence; `.env` is ignored by
Git. Both the key and a model supporting structured outputs must be configured
before running. `--model MODEL` overrides `CLAUDE_MODEL`.

Write structured JSON into one text file per index:

```bash
uv run python composer.py
uv run python composer.py --index "Melbourne Water" --limit 1
uv run python composer.py --output-dir /tmp/scraper-output --limit 1
```

The composer uses the same `INDEXES` list and passes each discovered source
unchanged to the existing HTML/PDF extraction helpers. Each extracted article is
then passed to Claude. `--index` matches a complete name, ignoring case. `--limit`
is a positive maximum per index for development; limited runs are labeled in the
terminal. Previously blocked indexes are not run.

By default files are saved under `output/`, which is ignored by Git. Each UTF-8
filename contains a sanitized index name and a short hash of its URL. Each `.txt`
contains a JSON array of accepted opportunity records, matching the
[ECHO opportunity contract](https://github.com/MCLWxMBI/website/blob/main/docs/contracts.md#opportunity).
It contains JSON only, with no text headers or error sections. Claude minimally
cleans `fullText` into ordered paragraphs, preserving the source wording and
detail while fixing obvious formatting artifacts. It also provides the title,
publisher, jurisdiction, dates, categories, tags, a 20–30-word summary, and
optional geography. Required nullable fields (`startDate` and `tags`) remain in
the JSON; absent summary and location fields are omitted.

For example, an index's text file has this structure:

```json
[
  {
    "id": "example-consultation",
    "title": "Example consultation",
    "fullText": ["The original extracted description."],
    "sourceUrl": "https://example.gov.au/example-consultation",
    "sourceOrg": "Example department",
    "jurisdiction": "Victoria",
    "startDate": null,
    "submissionDeadline": "2026-10-23T06:00:00Z",
    "category": ["Water & resources"],
    "tags": null,
    "summary": "A short description of the consultation."
  }
]
```

`id` comes from the article URL slug in Python, never from the title or Claude.
For treaty helper URLs ending in `Treaty_being_considered`, the parent inquiry
provides both the slug and official `sourceUrl`. Fragments and known tracking
parameters are removed; meaningful query parameters are preserved. Generic
query-based pages require one identifiable `slug`, `article`, `project`, or `id`
parameter. Ambiguous URLs are logged as invalid; different URLs producing the
same slug are reported as collisions. URL-derived IDs remain stable while the
publisher keeps the same article slug.

The Claude extraction model permits `submissionDeadline: null`. A listing is
accepted only when it has a valid deadline timestamp and validates against the
complete contract. Dates without a closing time or sufficient timezone
information remain unknown; Claude is instructed not to invent an instant.
`CLAUDE_RETRY_COUNT = 1` at the top of `structuring.py` allows one retry after an
unsuccessful response or API error, for two attempts total. SDK retries are
disabled. After exhaustion, the source URL and reason are logged as `INVALID` and
processing continues. Invalid listings are excluded from the JSON array.

Each selected index's file is overwritten on every run; files for other indexes
are left alone. Each attempt starts with `[]`. After every accepted listing, the
array is flushed to a temporary file and atomically replaces the index's output,
preserving the last completed save if interrupted. Empty indexes and indexes
with no accepted listings contain `[]`; skipped indexes create no file. The
terminal distinguishes empty results, invalid listings, failures, and limited
runs and prints a final summary. To retain those diagnostics in a scheduled run,
keep its terminal logs alongside the output artifacts.

Failures at one index or listing do not stop the rest. The composer exits `0` when
all attempted work succeeds (including listings rejected for missing deadlines
or invalid metadata), `1` for configuration/API/traversal/extraction/browser/file
errors or slug collisions, and `2` for invalid arguments. One synchronous API
client and one Chromium browser are reused and closed at the end. Collection
history, database storage, and GitHub Actions configuration are deferred. The
future scheduled workflow can supply the key through its environment, invoke the
composer, and retain its text files and logs.

Run the deterministic checks without a browser or network access:

```bash
uv run python -m unittest test_composer test_structuring test_opportunity test_traverse test_helpers
```
