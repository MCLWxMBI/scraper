# scraper

Open the project with **Dev Containers: Rebuild and Reopen in Container** in VS Code
to start the Python workspace and PostgreSQL 18. The app waits for the database
health check before starting. Database data persists in the `postgres-data` Docker
volume across container rebuilds.

From the devcontainer, connect to `postgres:5432` with database, username, and
password all set to `scraper` (local development credentials). The app container
sets the standard `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD`
environment variables, so `psycopg.connect()` can use them directly. The database
port is available within the Compose network. The scraper does not yet store
results in PostgreSQL.

Create the database tables and seed the website index catalogue manually:

```bash
uv run python setup_database.py
```

The command uses the existing `PG*` environment variables. It also loads `.env`
beside the script without overriding supplied environment variables. It requires
no Claude credentials and works with the existing persistent database volume.
SQL files are resolved relative to the script, so it can also be invoked by its
absolute path from another directory.

Setup applies `sql/schema.sql`, which creates both `public.website_indexes` and
`public.opportunities`. The index table uses the website project's schema and
upserts the 42 records from a reviewed local copy of its
[seed.sql](https://github.com/MCLWxMBI/website/blob/main/seed.sql): 40 active and
2 inactive. Rerunning restores every seed-owned field for IDs 1–42, including
locally edited activation flags, while preserving additional rows. Keep those
IDs reserved for the seed. Updating the upstream seed is an explicit code change;
the command does not fetch SQL from GitHub at runtime.

Existing index tables must match the expected columns, defaults, primary key,
and ID sequence settings. Setup verifies stored seed values before committing. Errors
roll back table creation and row changes and return exit code `1`; success
returns `0` with a summary. Run setup without concurrent catalogue writers. The
ID sequence is advanced as needed and never lowered; sequence changes can leave
gaps after rollback.

The opportunities table follows the
[opportunity contract](https://github.com/MCLWxMBI/website/blob/main/docs/contracts.md#opportunity)
and [persistence roadmap](https://github.com/MCLWxMBI/website/blob/main/docs/future-plans.md#opportunity-persistence).
It stores the stable text ID, title, ordered `full_text TEXT[]`, official source
URL and organisation, jurisdiction, nullable opening time, required deadline,
`category TEXT[] NOT NULL`, nullable `tags TEXT[]`, optional summary, and optional
`location JSONB`. Dates use `TIMESTAMPTZ`; API serialization must produce UTC
timestamps ending in `Z` and map snake-case column names to camelCase fields.
Status is derived from the dates rather than stored.

SQL checks enforce required content, supported jurisdictions/categories, date
order, nonempty arrays, trimmed array elements, case-insensitive uniqueness of
category/tag labels, and the basic location shape. No tags means SQL `NULL`,
not an empty array. Full HTTPS URL validation, plain-text validation, canonical
`Invite-only` spelling, and GeoJSON coordinate/ring validation belong to the
application's opportunity validation before inserts. Setup creates the table
but does not populate it or change the composer's file output. Reruns preserve
existing opportunities; `CREATE TABLE IF NOT EXISTS` does not migrate an existing
opportunities schema.

Upstream marks Barwon Water and VEWH inactive, but AEMC and GWMWater past projects
active. These flags are preserved even though local traversal blocks AEMC and
skips past projects. Discovery still uses the Python index lists; the catalogue
does not yet control scraper behavior or track processing history.

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
checks downstream. Results are kept in memory and printed; there is no processing
checkpoint, database-backed discovery, or scheduled workflow yet. A failed index
is reported separately from an empty listing; the remaining indexes continue and
the process exits nonzero.

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
history, opportunity database storage, and GitHub Actions configuration are
deferred. The future scheduled workflow can supply the key through its
environment, invoke the composer, and retain its text files and logs.

Run the deterministic checks without a browser or network access:

```bash
uv run python -m unittest test_composer test_structuring test_opportunity test_traverse test_helpers
uv run python -m unittest test_setup_database
```

Run the opt-in database setup integration checks against the Compose PostgreSQL
service from the devcontainer:

```bash
SETUP_DATABASE_INTEGRATION=1 uv run python -m unittest -v test_setup_database
```

Integration checks use the standard `PG*` environment and require a role with
`CREATEDB` permission (the local Compose role has it). They create uniquely named
test databases on that service and remove them afterward; the configured
`scraper` database is not modified by the tests.
