# scraper

Collect Victorian and Commonwealth environmental opportunities from active
website indexes, extract HTML/PDF content, and validate Claude responses before
saving them to PostgreSQL or JSON-array text files.

Open the project using **Dev Containers: Rebuild and Reopen in Container**. The
Compose app waits for PostgreSQL 18 to become healthy. Database data persists in
the `postgres-data` volume across rebuilds.

## Configuration and setup

Copy `.env.example` to `.env` and configure:

```dotenv
DATABASE_URL=postgresql://scraper:scraper@postgres:5432/scraper
ANTHROPIC_API_KEY=your-api-key
CLAUDE_MODEL=your-structured-output-model
```

The URL above works inside the local app container. All commands load the
repository-root `.env` using `override=False`, regardless of the working
directory. Supplied environment variables take precedence. A missing or blank
`DATABASE_URL` is an error; connections do not fall back to individual `PG*`
variables. `.env` is ignored by Git and credentials are not printed.

A future GitHub Actions workflow can invoke the root `main.py` and explicitly
map repository secrets into the step environment:

```yaml
env:
  DATABASE_URL: ${{ secrets.DATABASE_URL }}
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  CLAUDE_MODEL: ${{ secrets.CLAUDE_MODEL }}
```

That database must be reachable from the runner; `postgres` above is a local
Compose hostname. A workflow has not been added yet.

Install dependencies and initialize the database explicitly:

```bash
uv sync --locked
uv run playwright install --with-deps chromium
uv run python -m scraper setup-db
```

Setup needs no Claude credentials. It applies `sql/schema.sql` and upserts all
42 index records: **38 active and 4 inactive**. The local seed disables Barwon
Water, VEWH, AEMC, and GWMWater past projects; IDs 14 and 39 intentionally differ
from the [upstream seed](https://github.com/MCLWxMBI/website/blob/main/seed.sql).

Rerunning setup restores seed-owned values for IDs 1–42, including activation
flags, and preserves additional rows and existing opportunities. Existing index
schemas are checked before seeding. Table/row changes roll back on error;
sequence advancement never moves backward but may leave gaps after rollback.
Run setup without concurrent catalogue writers. Setup does not migrate an
existing opportunities schema. Collection never creates tables or reseeds.

## Commands

Run these commands from the repository root:

```bash
# Discover source URLs without extraction or Claude calls
uv run python -m scraper discover
uv run python -m scraper discover --index "Melbourne Water"

# Collect and save validated opportunities to PostgreSQL
uv run python main.py
uv run python main.py --index "Melbourne Water" --limit 1

# Save JSON-array .txt files and print source PASS/FAIL results
uv run python main.py --text --index "Melbourne Water" --limit 1
uv run python main.py --text --output-dir /tmp/scraper-output
```

`--txt` remains an alias for `--text`. `--output-dir` requires text mode and
defaults to `output/`. `--model MODEL` overrides `CLAUDE_MODEL`. For a command
launched elsewhere, use `uv run --directory /path/to/scraper ...`, or invoke the
absolute path to `main.py` with the project interpreter.

Both discovery and collection first query `website_indexes WHERE active = TRUE`,
ordered by case-insensitive name and ID. `--index` matches a complete active name,
ignoring case. Unknown/inactive names are argument errors. Empty active results
exit successfully before browser/Claude startup. Query failures stop the run;
there is no hard-coded fallback list. Past-project discovery safeguards remain.

`--limit N` currently selects at most N sources per index **after complete
source discovery**. It does not yet limit pagination. Limited work is labeled.
See the [roadmap](docs/roadmap.md) for planned discovery budgets and history.

## Local runs using saved articles

```bash
uv run python main.py --fixtures
uv run python main.py --fixtures --index "Coliban Water" --limit 1
uv run python main.py --fixtures --output-dir output/local-test
```

`--fixtures` reads the bundled historical article samples in
`tests/fixtures/wayback/manifest.json`. It starts at saved articles rather than
replaying listing discovery. HTML text extraction and the supported PDF routes
run locally; original article URLs remain the source identities and Claude
context. Referenced files are confined to the fixture directory and checked
against their SHA-256 checksums. Missing resources never trigger downloads.

**This mode calls real Claude and incurs API usage.** Set `ANTHROPIC_API_KEY`
and `CLAUDE_MODEL` as usual, or supply `--model`. No `DATABASE_URL`, PostgreSQL,
browser installation or website access is needed. The only network client used
during fixture runs is Claude. Automated tests mock Claude.

Results always use the usual JSON-array text files and PASS/FAIL reporting,
with `output/fixtures/` as the default destination. `--text` and `--txt` are
accepted but unnecessary. Repeated runs replace each selected index's file and
call Claude again; fixture mode does not implement processing history.

`--index` selects a manifest index by its full name, ignoring case, including
inactive seed indexes. `--limit` counts distinct saved article samples rather
than live discoveries. There are up to three samples per index. Indexes without
usable archived articles are skipped with their recorded coverage reason;
missing or corrupt files referenced by selected samples cause FAIL and a nonzero
exit. Read the [fixture README](tests/fixtures/wayback/README.md) for provenance,
archive gaps and how to extend the collection. Fixtures are never refreshed by
ordinary test runs.

## Runtime flow and file responsibilities

```mermaid
flowchart TD
    Main["main.py"] --> Pipeline["pipeline.py: collection"]
    Commands["scraper/__main__.py"] --> Discovery["discovery.py: discover source URLs"]
    Commands --> Setup["db/setup.py"]
    Pipeline --> Config["config.py: paths and .env"]
    Discovery --> Config
    Setup --> Config
    Config --> Connection["db/connection.py: DATABASE_URL"]
    Connection --> Indexes["db/indexes.py: active indexes"]
    Pipeline --> Discovery
    Pipeline --> Fixtures["fixtures.py: saved article manifest with --fixtures"]
    Fixtures --> Extraction
    Indexes --> Discovery
    Discovery --> Sources["models.py: Source"]
    Sources --> Extraction["extraction.py: rendered HTML / PDF text"]
    Extraction --> Structuring["structuring.py: Claude and validation"]
    Structuring --> Opportunity["models.py: Opportunity"]
    Opportunity --> Database["db/opportunities.py: committed upsert"]
    Opportunity --> Text["text_export.py: atomic JSON file"]
    Setup --> Schema["sql/schema.sql"]
    Setup --> Seed["sql/seed_website_indexes.sql"]
```

| File | Responsibility and flow |
| --- | --- |
| `main.py` | Root collection entry point for local runs and Actions; forwards arguments and returns the pipeline exit code. |
| `scraper/__main__.py` | Routes `discover` to discovery and `setup-db` to explicit database setup. |
| `scraper/__init__.py`, `scraper/db/__init__.py` | Define the application and database packages without running collection. |
| `scraper/config.py` | Resolves repository-root `.env` and SQL paths; loads environment defaults without overriding supplied values. |
| `scraper/models.py` | Defines immutable `Source` objects, opportunity fields, and validated geography/content models. |
| `scraper/discovery.py` | Reads active indexes for its CLI, traverses supported listings and pagination, and returns original routing-aware Sources. |
| `scraper/extraction.py` | Renders each source, waits for stable content, and extracts HTML text or the supported special PDFs. |
| `scraper/fixtures.py` | Loads the bundled historical manifest, verifies local HTML/PDF resources, and supplies original Sources and saved article text without HTTP or a browser. |
| `scraper/structuring.py` | Calls Claude, validates the response, derives canonical source identity, and returns a complete Opportunity. |
| `scraper/pipeline.py` | Owns the collection CLI and resource lifecycle; orchestrates discovery, extraction, validation, persistence, and terminal summaries. |
| `scraper/text_export.py` | Generates stable per-index filenames and atomically replaces JSON-array text files. |
| `scraper/db/connection.py` | Connects using DATABASE_URL with a bounded timeout and sanitized diagnostics. |
| `scraper/db/indexes.py` | Retrieves all active index names/URLs in deterministic order. |
| `scraper/db/opportunities.py` | Maps models to SQL parameters, checks table access, and transactionally upserts records while protecting against cross-URL slug collisions. |
| `scraper/db/setup.py` | Applies schema, checks index-table compatibility, seeds and verifies records, and advances the ID sequence. |
| `sql/schema.sql` | Defines website indexes, opportunities, and basic opportunity constraints. |
| `sql/seed_website_indexes.sql` | Holds the reviewed, pinned index seed with documented local exclusions; returns expected values for verification. |

Tests live in `tests/`. [Source notes](docs/source-notes.md) record discovery
ordering findings; [the roadmap](docs/roadmap.md) records future work.
`.agents/current-state.md` contains agent handoff information.

## Persistence and text-mode results

Default mode checks opportunity-table access before extraction and commits each
validated opportunity independently. It creates no output files or directories.
A record with the same ID and source URL is updated; a different URL sharing an
ID fails without overwriting the stored record. Empty/invalid-only runs leave
existing records untouched. Write failures do not count as successful saves.

Live text mode still needs the database to read active indexes. It closes that
connection before collection and makes no opportunity writes. Each attempted
source prints one final result, including its original URL:

```text
PASS https://example.gov.au/project
FAIL https://example.gov.au/other — No deadline timestamp returned
```

`PASS` is printed only after validation and a successful file save. `FAIL`
includes invalid metadata, missing deadlines, URL/slug problems, extraction/API
errors, and file-save failures, with a reason. Index and run summaries combine
these into PASS/FAIL counts. Skipped indexes and intentionally limited work are
reported separately; traversal failures identify the index URL.

Failures do not introduce error sections into files. Each selected index starts
with `[]`, then its UTF-8 `.txt` file is atomically updated after each accepted
listing. Filenames contain a sanitized index name plus a URL hash. Files for
other indexes remain untouched. Files contain only that run's successful records:

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
    "tags": null
  }
]
```

Normal invalid rejections count as FAIL in text output but do not by themselves
make the command fail. Exit codes remain `0` for completed work, `1` for
configuration or operational errors/collisions, and `2` for argument errors.

## Opportunity validation and database mapping

The model follows the [ECHO opportunity contract](https://github.com/MCLWxMBI/website/blob/main/docs/contracts.md#opportunity)
and [persistence requirements](https://github.com/MCLWxMBI/website/blob/main/docs/future-plans.md#opportunity-persistence).
Claude returns minimally cleaned, ordered full-text paragraphs and a separate
20–30-word summary. Wording and detail are preserved in full text. The complete
extracted text is supplied to Claude with the index name and canonical URL.

Extraction permits a null deadline; accepted opportunities require an
authoritative UTC timestamp ending in `Z`. Do not infer closing times or
coordinates. One initial attempt plus one retry is the complete Claude attempt
budget; SDK retries are disabled. The model is explicitly configured, with no
hard-coded default.

IDs come from URL slugs, not titles or Claude. Canonicalization removes known
tracking parameters and fragments while preserving meaningful queries. Treaty
helper URLs map to the parent inquiry. Ambiguous URLs and cross-URL slug
collisions are rejected.

SQL uses snake-case columns, `TIMESTAMPTZ` dates, ordered `TEXT[]` full text,
required `category TEXT[]`, nullable `tags TEXT[]`, optional summary, and optional
`location JSONB`. SQL checks basic content, dates, arrays, supported values, and
location shape; the application validates full URLs and GeoJSON coordinates and
rings. There is no stored open/upcoming/closed status. API serialization must
map field names, render UTC dates ending in `Z`, preserve required nulls, and
omit absent summary/location.

`opportunity_parameters()` and `save_opportunity()` are available in
`scraper.db.opportunities`. The writer uses a savepoint inside an existing
transaction; its caller owns the connection and outer commit. Composer uses an
autocommit connection so each record's transaction commits independently.
Processing-history tracking and refresh rules remain deferred.

## Validation

Run deterministic tests without a browser, database connection, or API calls:

```bash
uv run python -m unittest discover -s tests -t .
```

Run opt-in PostgreSQL integration tests on the Compose service:

```bash
SETUP_DATABASE_INTEGRATION=1 uv run python -m unittest tests.test_setup
```

Integration checks load DATABASE_URL from `.env` or the environment and require
`CREATEDB` (available to the Compose role). They create uniquely named test
databases, mock browser/Claude operations, and remove the test databases afterward.
The configured persistent database is not modified by the tests.
