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

The URL above works inside the local app container. Application commands load the
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
41 index records: **38 active and three inactive**. Barwon Water (8), VEWH
(24) and AEMC (38) remain inactive. GWMWater past projects was removed and later
IDs were renumbered. Gippsland collects future projects, Wannon collects In
planning projects, and Western Port collects current projects. These local
choices differ from the [upstream seed](https://github.com/MCLWxMBI/website/blob/main/seed.sql).

Rerunning setup restores seed-owned values for IDs 1–41, including activation
flags, and preserves additional rows and existing opportunities. Existing index
schemas are checked before seeding. Table/row changes roll back on error;
sequence advancement never moves backward but may leave gaps after rollback.
Run setup without concurrent writers. Setup adds article history and deletion
triggers; it does not migrate incompatible opportunity columns. It refuses
existing opportunities without successful history rather than guessing content
hashes or deleting data. Collection never creates tables or reseeds.

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
The limit counts canonical candidates before history filtering and article extraction;
skipped candidates are not replaced. See the [roadmap](docs/roadmap.md) for
remaining discovery-budget and scheduling work.

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
    Discovery --> History["db/history.py: hashes and deleted URLs"]
    Extraction --> Gate["discovery.py: compare live content; fixtures bypass history"]
    Gate --> Decisions["decision_log.py: file-only JSONL decisions"]
    Gate --> Structuring["structuring.py: Claude and validation"]
    Structuring --> Opportunity["models.py: Opportunity"]
    Opportunity --> Database["db/opportunities.py: committed upsert"]
    Opportunity --> Text["text_export.py: atomic JSON file"]
    Database --> Decisions
    Text --> Decisions
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
| `scraper/discovery.py` | Traverses listings and pagination; live collection prepares article text, checks history, and returns only new/changed work plus skip/error outcomes. Its standalone CLI remains a raw URL-discovery diagnostic. |
| `scraper/extraction.py` | Renders each source, waits for stable content, and extracts HTML text or the supported special PDFs. |
| `scraper/identity.py` | Defines shared canonical source URLs, normalized Claude input text and SHA-256 content hashes. |
| `scraper/fixtures.py` | Loads the bundled historical manifest, verifies local HTML/PDF resources, and supplies original Sources and saved article text without HTTP or a browser. |
| `scraper/structuring.py` | Calls Claude, validates the response, derives canonical source identity, and returns a complete Opportunity. |
| `scraper/pipeline.py` | Owns the collection CLI and resource lifecycle; orchestrates discovery, extraction, validation, persistence, and terminal summaries. |
| `scraper/decision_log.py` | Writes file-only JSONL article decisions, including hash comparisons and committed save outcomes; never installs a console handler. |
| `scraper/text_export.py` | Generates stable per-index filenames and atomically replaces JSON-array text files. |
| `scraper/db/connection.py` | Connects using DATABASE_URL with a bounded timeout and sanitized diagnostics. |
| `scraper/db/indexes.py` | Retrieves all active index names/URLs in deterministic order. |
| `scraper/db/history.py` | Batch-reads last successful content hashes and persistent deletion markers; lookup failures stop processing. |
| `scraper/db/opportunities.py` | Atomically saves an opportunity and its input hash, rejecting deleted identities and cross-URL slug collisions. |
| `scraper/db/setup.py` | Applies schema, checks index-table compatibility, seeds and verifies records, and advances the ID sequence. |
| `scripts/test_history_replay.sh` | Resolves the project root and invokes the discovery-only historical replay runner. |
| `tests/history_replay.py` | Replays saved listing membership through real discovery preparation against an isolated Compose PostgreSQL database, then cleans up. |
| `sql/schema.sql` | Defines indexes, opportunities, article history, constraints, and row-locking deletion/protection triggers. |
| `sql/reset_articles.sql` | Manually truncates opportunities and history in a disposable database; bypasses deletion triggers and preserves website indexes. Never run automatically. |
| `sql/seed_website_indexes.sql` | Holds the reviewed, pinned index seed with documented local exclusions; returns expected values for verification. |

Tests live in `tests/`. [Source notes](docs/source-notes.md) record discovery
ordering findings; [the roadmap](docs/roadmap.md) records future work.
`.agents/current-state.md` contains agent handoff information.

## Persistence and text-mode results

Default mode checks opportunity/history table access before extraction and commits
each validated opportunity together with its successful input hash. It creates no output files or directories.
A record with the same ID and source URL is updated; a different URL sharing an
ID fails without overwriting the stored record. Empty/invalid-only runs leave
existing records untouched. Write failures do not count as successful saves.

Live text mode keeps a database connection to read active indexes and article
history. It skips unchanged/deleted articles, but makes no opportunity or history
writes: a new text-only result must not prevent a later database import. Each attempted
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

## Content history and deleting opportunities

Live collection fully discovers eligible URLs across sections and pagination.
At the discovery preparation stage it batch-loads `article_history`, skips
`deleted` URLs before article-body downloads (including treaty helper pages),
and extracts the remaining HTML/PDF text. Only new or changed content proceeds
to Claude; the pipeline reuses that prepared text without downloading it again.
The standalone `python -m scraper discover` command remains raw URL discovery
without article extraction, history filtering or Claude calls.

History uses the canonical `source_url` as its primary key, a descriptive
`title`, a last-successful content `hash`, and `deleted BOOLEAN DEFAULT FALSE`.
The hash is SHA-256 of exactly the normalized input sent to Claude: CRLF/CR
become LF and outer whitespace is stripped. Hashes are not unique across URLs.
This compares extracted text, not raw HTML, listing positions, or titles alone.
Changes to navigation retained by the existing extractor can also change a hash.

After validation, the opportunity and its hash commit in one transaction.
Extraction, validation, API and storage failures leave the prior successful
hash untouched and remain eligible on the next run. `SKIPPED (unchanged)` and
`SKIPPED (deleted)` are reported separately from source PASS/FAIL outcomes.
History lookup failures stop collection before further Claude processing.

Delete the actual opportunity row using ordinary SQL:

```sql
DELETE FROM public.opportunities WHERE id = 'opportunity-id';
```

The `AFTER DELETE` trigger atomically retains a history row with `deleted=TRUE`
and preserves any prior hash. It creates a marker even for an untracked row;
its hash can be NULL. Deleting a post therefore cannot cause it to be scraped
again, even if its source content later changes. Insert/update protection and
a guarded history upsert prevent a late scraper save from clearing that marker.
No cascading foreign key removes history with the opportunity.

To deliberately reimport, ensure the opportunity is gone, then explicitly delete
its matching canonical `source_url` from `public.article_history`. Normal saves
never reset `deleted` to false. All opportunity writers must use canonical URLs.
`TRUNCATE` bypasses row-level deletion triggers; use `DELETE` for post removal.

Run `uv run python -m scraper setup-db` manually to install the table/triggers
before live collection. Initial setup refuses unexpected existing opportunities
without successful history. For a **disposable local development database only**, after
exporting `DATABASE_URL` in your shell, the explicit reset command is:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/reset_articles.sql
```

This transactionally clears opportunities and article history when present,
including deletion markers, and leaves website indexes untouched. Setup and
collection never invoke this reset. Real existing data needs a separately
planned migration; do not reset it. Integration tests apply setup only inside
a uniquely named test database on the devcontainer PostgreSQL service, then drop
that database. They do not change the configured `scraper` development database.

Only one collector should run at a time. Deletion can race with already-prepared
or running Claude work; the guarded save still rejects a deleted identity. A crash after Claude responds but before
commit can require another call. PostgreSQL history tests use saved Wayback fixtures against the actual
devcontainer PostgreSQL service. SQL, transactions, deletion triggers and lock
waits are real; only Claude responses and website/browser navigation are mocked.

```bash
uv run python -m unittest tests.test_fixtures
```

The history test role needs `CREATEDB`. By default tests target the Compose
`postgres:5432/scraper` connection; `ARTICLE_HISTORY_TEST_DATABASE_URL` can select
another explicit development PostgreSQL connection. They do not load `.env` or
fall back to a potentially remote application database.

## Article decision logs and historical deduplication replay

Collection appends article decisions to `output/logs/scraper.jsonl`, resolved
relative to the project root. Override it with `main.py --log-file PATH`.
The JSONL events stay out of terminal PASS/FAIL output and JSON-array `.txt`
files. Each event includes its run, UTC timestamp, index, original/canonical
source URL and decision: `new`, `changed`, `unchanged`, `deleted`, `failed` or
`saved`. Hash comparisons include previous/current hashes where available.
Exception details, extracted bodies and credentials are not logged. A log-file
failure stops processing rather than silently redirecting events to the console.

`new` and `changed` mean eligible for Claude, not successfully processed.
`saved` in database mode means the write committed; a writer used inside an
outer transaction does not emit a committed-save event. A text-save event has
`destination="text"` and `history_advanced=false`; it does not make later database
collection skip that article. Ordinary `--fixtures` still bypasses history and
still calls real Claude.

Run the **discovery-only** older/newer check with:

```bash
./scripts/test_history_replay.sh
./scripts/test_history_replay.sh --index "Coliban Water"
```

This script does **not invoke Claude**, initialize a browser, request websites,
or require Claude credentials. It creates a temporary database on the actual
Compose PostgreSQL service, validates all 116 bundled resources, then feeds
recorded ordered listing entries into production discovery preparation. It
primes real test history rows between the older, newer and repeated-newer
stages to represent prior successful processing. It does not create opportunities
or pretend to validate historical articles with Claude. The configured `scraper`
database and fixture files remain unchanged. The test role needs `CREATEDB`;
`ARTICLE_HISTORY_TEST_DATABASE_URL` can override the explicit devcontainer test
connection, independently of application `.env` settings.

Logs and `summary.json` are retained under `output/history-replay/<run-id>/`.
`passed` means the selected pair exercises both shared ready articles and ready
arrivals. `partial` identifies narrower checks, `empty` identifies explicit
empty consultation states, and `skipped` identifies missing coverage. Test
assertions, corrupt fixtures and operational errors exit nonzero. Coverage gaps
are explicit and do not count as passing deduplication comparisons.

Shared URLs deliberately reuse the same saved body across stages. This proves
unchanged-content deduplication, not historical equality between article captures.
The runner uses listing membership recorded in the manifest and checked against
saved HTML; it does not replay browser pagination. See the full
[41-index comparison schedule and limitations](docs/history-replay.md).

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
Live discovery now compares extracted-content hashes with successful history.
Invalid results and failures remain retryable. Fixture replay bypasses history.

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
