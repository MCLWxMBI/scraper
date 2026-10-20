# scraper

Open the project with **Dev Containers: Rebuild and Reopen in Container** in VS Code
to start the Python workspace and PostgreSQL 18. The app waits for the database
health check before starting. Database data persists in the `postgres-data` Docker
volume across container rebuilds.

Configure `DATABASE_URL` in `.env` for local development inside the app
container:

```dotenv
DATABASE_URL=postgresql://scraper:scraper@postgres:5432/scraper
```

The database port is available within the Compose network. All commands load
`.env` beside the scripts with `override=False`: existing environment variables
win. A missing or blank `DATABASE_URL` is an error; application connections do
not fall back to the individual `PG*` settings.

In a future GitHub Actions workflow, explicitly map repository secrets into the
step's environment (no `.env` file is required):

```yaml
env:
  DATABASE_URL: ${{ secrets.DATABASE_URL }}
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  CLAUDE_MODEL: ${{ secrets.CLAUDE_MODEL }}
```

The Actions database URL must point to a database reachable from that runner;
the `postgres` hostname above belongs to the local Compose network.

Create the database tables and seed the website index catalogue manually:

```bash
uv run python setup_database.py
```

The command connects using `DATABASE_URL`. It requires no Claude credentials and
works with the existing persistent database volume.
SQL files are resolved relative to the script, so it can also be invoked by its
absolute path from another directory.

Setup applies `sql/schema.sql`, which creates both `public.website_indexes` and
`public.opportunities`. The index table uses the website project's schema and
upserts the 42 records from a reviewed local copy of its
[seed.sql](https://github.com/MCLWxMBI/website/blob/main/seed.sql): 38 active and
4 inactive. Rerunning restores every seed-owned field for IDs 1–42, including
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
but does not populate it. Composer populates it during database-mode runs. Reruns preserve
existing opportunities; `CREATE TABLE IF NOT EXISTS` does not migrate an existing
opportunities schema.

`opportunity_storage.py` provides `opportunity_parameters(opportunity)` and
`save_opportunity(connection, opportunity)` for validated `Opportunity` models.
The mapper converts camelCase model fields to SQL column names, UTC timestamp
strings to timezone-aware datetimes, and location to Psycopg `Jsonb`. Absent
optional fields become SQL `NULL`.

After schema setup, callers can persist a validated model using the existing
`DATABASE_URL` configuration:

```python
from database import connect_database, load_environment
from opportunity_storage import save_opportunity

load_environment()
with connect_database(autocommit=True) as connection:
    save_opportunity(connection, opportunity)  # A validated Opportunity model
```

The writer inserts or updates by opportunity ID only when the stored source URL
matches. A different URL using the same ID raises `OpportunityStorageError`
without overwriting the stored record. Each call runs in a transaction; inside
an existing transaction it uses a savepoint and leaves the outer commit to the
caller. The caller owns the connection and environment loading. Database error
messages are sanitized. Composer uses this writer by default.

The local seed disables Barwon Water, VEWH, AEMC, and GWMWater past projects.
IDs 14 and 39 are intentional adjustments to the upstream seed to reflect the
existing past-project and blocked-site exclusions. Rerun setup to apply these
flags to an existing database. Collection never automatically runs setup or
reseeds the catalogue.

Discover source pages using synchronous Playwright:

```bash
uv sync --locked
uv run playwright install --with-deps chromium
uv run python traverse.py
uv run python traverse.py --index "Melbourne Water"
```

Both commands query `public.website_indexes WHERE active = TRUE` at startup,
ordered by case-insensitive name and ID. `--index` matches a complete active
name, ignoring case; unknown or inactive names are argument errors. Edit
activation flags in the database to control collection. The historical Python
lists are no longer used for command-line index selection. Past-project route
safeguards remain in traversal.

Database lookup failures stop the run, with no fallback to local lists. No
active indexes means a successful no-op before browser or Claude startup.
`traverse.py` prints discovered URLs; `composer.py` processes those discoveries.

Traversal discovers open/upcoming consultations and current project candidates.
News, bills, and uncertain project candidates still need eligibility and relevance
checks downstream. Results are kept in memory and printed; there is no processing
history checkpoint or scheduled workflow yet. A failed index
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

Save validated opportunities to PostgreSQL by default, or select text output:

```bash
uv run python composer.py
uv run python composer.py --index "Melbourne Water" --limit 1
uv run python composer.py --txt --output-dir /tmp/scraper-output --limit 1
```

The composer reads active indexes from PostgreSQL and passes each discovered source
unchanged to the existing HTML/PDF extraction helpers. Each extracted article is
then passed to Claude. `--index` matches a complete name, ignoring case. `--limit`
is a positive maximum per index for development; limited runs are labeled in the
terminal. Both output modes require `DATABASE_URL` to load active indexes.
`--output-dir` requires `--txt`.

Default mode checks opportunity-table access before collection, then commits each
validated opportunity independently. Existing records with the same ID and URL
are updated; cross-URL ID collisions fail without overwriting data. Database
mode creates no output files or directories. Empty and invalid-only indexes
leave existing records untouched. Write failures are reported, cause exit `1`,
and do not count as successes; remaining listings continue.

`--txt` closes its database connection after index selection and performs no
opportunity writes.

With `--txt`, files are saved under `output/` by default, which is ignored by Git. Each UTF-8
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
processing continues. Invalid listings are excluded from the selected output.

In text mode, each selected index's file is overwritten on every run; files for
other indexes are left alone. Each attempt starts with `[]`. After every accepted
listing, the array is flushed to a temporary file and atomically replaces the index's output,
preserving the last completed save if interrupted. Empty indexes and indexes
with no accepted listings contain `[]`; skipped indexes create no file. The
terminal distinguishes empty results, invalid listings, failures, and limited
runs and prints a final summary. To retain those diagnostics in a scheduled run,
keep its terminal logs alongside the output artifacts.

Failures at one index or listing do not stop the rest. The composer exits `0` when
all attempted work succeeds (including listings rejected for missing deadlines
or invalid metadata), `1` for configuration/API/traversal/extraction/browser/file
or database errors or slug collisions, and `2` for invalid arguments. One
synchronous API client and one Chromium browser are reused and closed at the
end. Collection history and GitHub Actions configuration remain deferred. The
future scheduled workflow can supply configuration through its environment,
invoke composer, and retain its logs and any requested text files.

Run the deterministic checks without a browser or network access:

```bash
uv run python -m unittest test_composer test_structuring test_opportunity test_traverse test_helpers
uv run python -m unittest test_setup_database
uv run python -m unittest test_opportunity_storage test_database
```

Run the opt-in database setup integration checks against the Compose PostgreSQL
service from the devcontainer:

```bash
SETUP_DATABASE_INTEGRATION=1 uv run python -m unittest -v test_setup_database
```

Integration checks load `DATABASE_URL` from `.env` or the environment and require
a role with `CREATEDB` permission (the local Compose role has it). They create
uniquely named test databases on that service and remove them afterward; the configured
`scraper` database is not modified by the tests.
