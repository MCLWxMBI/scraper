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

Local collection uses `ANTHROPIC_API_KEY`. GitHub Actions uses Anthropic OIDC
instead: `create_claude_client()` selects federation when any of its four
`ANTHROPIC_*_ID` settings below is configured; otherwise it requires an API key.
Incomplete federation configuration is an error, with no API-key fallback.
Unset `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` when using federation;
conflicting static credentials are rejected. The Claude model, prompts and
one-call-per-article policy are the same with either authentication method.

Install dependencies and initialize the database explicitly:

```bash
uv sync --locked
uv run playwright install --with-deps chromium
uv run python -m scraper setup-db
```

### Daily production collection with GitHub Actions

[Daily scraper](.github/workflows/scraper.yml) runs at **14:00 UTC daily**:
**01:00 AEDT / 00:00 AEST on the next local day**. Scheduled starts are best
effort and can be delayed. To run manually, open **Actions → Daily scraper →
Run workflow** and select the default branch. Runs on other branches are
skipped. Both triggers use the shared production concurrency group and a
six-hour timeout; an active run is not cancelled by a newer invocation.

Under **Settings → Secrets and variables → Actions**, configure:

| Type | Name | Value |
| --- | --- | --- |
| Repository secret | `DATABASE_URL` | Production PostgreSQL URL, including the provider's required TLS parameters. |
| Repository variable | `CLAUDE_MODEL` | Supported structured-output model ID. |
| Repository variable | `ANTHROPIC_ORGANIZATION_ID` | Anthropic organization ID. |
| Repository variable | `ANTHROPIC_FEDERATION_RULE_ID` | Anthropic federation rule ID (`fdrl_...`). |
| Repository variable | `ANTHROPIC_SERVICE_ACCOUNT_ID` | Service account ID (`svac_...`). |
| Repository variable | `ANTHROPIC_WORKSPACE_ID` | Workspace ID (`wrkspc_...`). |

No `ANTHROPIC_API_KEY` secret is needed. In the Claude Console's **Workload
identity → Connect workload → GitHub Actions** setup, register the GitHub
issuer, choose a service account with membership in the target workspace, and
configure the federation rule to trust only this repository, its default branch
and `.github/workflows/scraper.yml`. Match the repository's actual OIDC claims,
including `ref`, `workflow_ref` and `event_name` (`schedule` or
`workflow_dispatch`), using the rule's conditions. Use audience
`https://api.anthropic.com`. See [Anthropic's GitHub Actions OIDC guide](https://platform.claude.com/docs/en/manage-claude/wif-providers/github-actions).

The workflow grants `contents: read` and `id-token: write`. GitHub automatically
provides the identity-request URL and credential. The SDK's token provider
fetches fresh identity tokens when required and exchanges them for short-lived
Anthropic access tokens; long runs do not depend on a single startup token.
Neither identity tokens nor access tokens are written to files or logged.
Local `.env` API-key runs continue to work without OIDC configuration.

Run authentication and workflow checks without real credentials, database access
or Claude charges:

```bash
uv run python -m unittest tests.test_auth tests.test_workflow
```

The runner installs Python 3.13, locked dependencies and Chromium, then runs
`uv run --frozen python -u main.py` against all active production indexes.
Real Claude usage is charged. Existing article history controls skips; valid
opportunities and history commit together. Operational errors fail the job;
ordinary invalid articles retain their existing rejection behavior. The
workflow never initializes, reseeds or resets a database. Production must
already have the current schema and indexes and be reachable from the runner;
`postgres` in the local example is a Compose-only hostname.

The Actions console retains normal progress and skipped counts. The
`scraper-logs-<run-id>-<attempt>` artifact contains `actions-run.txt` (console
stdout/stderr) and `scraper.jsonl` (article decisions) when available, uploaded
after success or failure with 14-day retention. Console capture preserves the
scraper's nonzero exit status. There is no automatic collection retry.

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

# Save JSON-array .txt files, extracted article text, and source PASS/FAIL results
uv run python main.py --text --index "Melbourne Water" --limit 1
uv run python main.py --text --output-dir /tmp/scraper-output
```

`--txt` remains an alias for `--text`. `--output-dir` requires text mode and
defaults to `output/`. `--model MODEL` overrides `CLAUDE_MODEL`. For a command
launched elsewhere, use `uv run --directory /path/to/scraper ...`, or invoke the
absolute path to `main.py` with the project interpreter.

Text mode also writes the exact normalized HTML/PDF extractor text **before
Claude** under the repository-root `output/raw/`, with one folder per index and
one UTF-8 `.txt` file per article:

```text
output/raw/
└── coliban-water-b1863f0cf3eb/
    ├── malmsbury-culvert-restoration-<url-hash>.txt
    └── rural-water-efficiency-<url-hash>.txt
```

These files contain plain extracted text, without JSON, metadata headers or
Claude-generated summaries. Safe names include URL hashes, so articles with the
same name or meaningful query variations remain distinct. Project sidebars, key
dates, news and collapsed FAQs/tabs are retained; known account/legal modal
containers are excluded. Timeline milestones are not inferred as feedback
deadlines. Corrected extraction changes content hashes and can make a previously
processed page eligible again. `--output-dir` moves
only the structured JSON-array files; raw files always stay under project
`output/raw/`, including when invoked from another directory.

Raw text remains available when Claude rejects an article or an API/structured
save fails. Live unchanged articles refresh their raw files and still skip
Claude; deleted articles are not extracted or exported. Text mode makes no
history writes. Extraction failures create no new raw file. Successful exports
atomically replace that article's file and leave other files untouched, so an
existing file can come from an earlier run. A failed replacement preserves the
last successful bytes. A raw-save error reports FAIL, skips Claude for that
article and makes the run exit nonzero while other sources continue. PASS still
requires successful structured output. Default PostgreSQL-output mode writes no
raw files. Raw export adds no extraction-only mode: normal text/fixture runs
continue their existing Claude processing and require its credentials.

Both discovery and collection first query `website_indexes WHERE active = TRUE`,
ordered by case-insensitive name and ID. `--index` matches a complete active name,
ignoring case. Unknown/inactive names are argument errors. Empty active results
exit successfully before browser/Claude startup. Query failures stop the run;
there is no hard-coded fallback list.

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
with `output/fixtures/` as the default destination. Raw article files are also
written automatically under project `output/raw/<index-folder>/`. `--text` and `--txt` are
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
    Main --> RunLog["run_log.py: text-mode terminal transcript under output/logs/"]
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
    Structuring --> Geography["locations.py: verified geometry; no second Claude call"]
    Geography --> Opportunity["models.py: Opportunity"]
    Opportunity --> Database["db/opportunities.py: committed upsert"]
    Opportunity --> Text["text_export.py: atomic JSON file"]
    Database --> Decisions
    Pipeline --> Raw["text_export.py: output/raw/ extracted article text in text mode"]
    Text --> Decisions
    Setup --> Schema["sql/schema.sql"]
    Setup --> Seed["sql/seed_website_indexes.sql"]
```

| File | Responsibility and flow |
| --- | --- |
| `main.py` | Root collection entry point for local runs and Actions; forwards arguments and returns the pipeline exit code. |
| `scraper/__main__.py` | Routes `discover` to discovery and `setup-db` to explicit database setup. |
| `scraper/__init__.py`, `scraper/db/__init__.py` | Define the application and database packages without running collection. |
| `scraper/dates.py` | Computes date-only structuring metadata in Australia/Sydney, independently of host timezone. |
| `scraper/config.py` | Resolves repository-root `.env` and SQL paths; loads environment defaults without overriding supplied values. |
| `scraper/auth.py` | Creates API-key or GitHub OIDC Claude clients, obtains fresh identity tokens for SDK refresh, and sanitizes authentication failures. |
| `.github/workflows/scraper.yml` | Runs full production collection daily or manually using OIDC and a production database secret; retains console and decision logs. |
| `scraper/models.py` | Defines immutable Source/WebsiteIndex context, opportunity fields, internal processing metadata, and validated geography/content models. |
| `scraper/discovery.py` | Traverses listings and pagination; live collection prepares article text, checks history, and returns only new/changed work plus skip/error outcomes. Its standalone CLI remains a raw URL-discovery diagnostic. |
| `scraper/extraction.py` | Renders each source, waits for stable content, and extracts HTML text or the supported special PDFs. |
| `scraper/identity.py` | Defines shared canonical source URLs, normalized Claude input text and SHA-256 content hashes. |
| `scraper/fixtures.py` | Loads the bundled historical manifest, verifies local HTML/PDF resources, and supplies original Sources and saved article text without HTTP or a browser. |
| `scraper/structuring.py` | Makes one Claude call for metadata and geographic scope, resolves geography, and returns a validated Opportunity. |
| `scraper/locations.py` | Resolves evidenced places through official geographic APIs or supplied verified candidates, validates scope and topology, and records location decisions without caching. |
| `scraper/pipeline.py` | Owns the collection CLI and resource lifecycle; orchestrates discovery, extraction, validation, persistence, and terminal summaries. |
| `scraper/run_log.py` | Copies text-mode CLI stdout/stderr into a unique, flushed UTF-8 run transcript; restores streams and reports file errors safely. |
| `scraper/decision_log.py` | Writes file-only JSONL article decisions, including hash comparisons and committed save outcomes; never installs a console handler. |
| `scraper/text_export.py` | Generates stable index/article filenames and atomically writes structured JSON-array files and raw UTF-8 article text. |
| `scraper/db/connection.py` | Connects using DATABASE_URL with a bounded timeout and sanitized diagnostics. |
| `scraper/db/indexes.py` | Retrieves active website IDs, names and URLs in deterministic order and retains IDs through collection. |
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

Each index summary includes its article skip count, including zero. Unchanged
and deleted articles count as skipped; candidates outside `--limit` do not.
Database and text modes both report the count, for example:

```text
Melbourne Water: COMPLETE: 2 valid, 0 invalid, 5 skipped; output=PostgreSQL
Melbourne Water: COMPLETE: 2 PASS, 0 FAIL, 5 skipped; output=output/melbourne-water-62822941dcc9.txt
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
`title`, a last-successful content `hash`, `deleted BOOLEAN DEFAULT FALSE`, a required
`upload_date DATE`, and nullable `source_index_id` referencing `website_indexes.id`.
The website ID is retained from the initial index query, not inferred from an
article URL or looked up separately for each article.

`upload_date` is captured immediately before the first successfully saved
structuring attempt, using the calendar date in `Australia/Sydney` (AEST/AEDT).
It is a date-only `YYYY-MM-DD`, with no timezone attached; do not convert the
Sydney date through UTC. Both fields are saved with the real title and successful
content hash in the same transaction as the opportunity. Discovery stays read-only:
there are no provisional rows, placeholder titles or null-hash discovery records.
Failed structuring or persistence creates no new history. Updates retain the first
upload date and website index ID; an unknown index ID can be filled when later known.
The date has a Sydney-date database default for direct/trigger insertion paths,
so `upload_date=NULL` is rejected. Deletion preserves both fields; deleting an index
sets its history references to NULL without removing history or deletion markers.
The hash is SHA-256 of exactly the normalized input sent to Claude: CRLF/CR
become LF and outer whitespace is stripped. Hashes are not unique across URLs.
This compares extracted text, not raw HTML, listing positions, or titles alone.
Changes to navigation retained by the existing extractor can also change a hash.

After validation, the opportunity and its hash commit in one transaction.
Article extraction, metadata validation, Claude API and storage failures leave
the prior successful hash untouched and remain eligible on the next run. `SKIPPED (unchanged)` and
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

To clear only history in the devcontainer `scraper` database, run inside the
devcontainer (stop collection first):

```bash
./scripts/reset_history.sh
```

This preserves opportunities and website indexes, but removes all successful
hashes and deletion markers, making those articles eligible for processing again.
It targets the Compose PostgreSQL service directly and ignores `DATABASE_URL`.

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

When `--text`, `--txt` or `--fixtures` is used, each CLI invocation also creates
`output/logs/<run-id>.txt` relative to the project root and prints its location.
It preserves the usual terminal output while copying Python stdout/stderr
messages: extraction progress, Claude starts, validation errors,
PASS/FAIL, skips and summaries. For example:

```text
Coliban Water: structuring with Claude: https://connect.coliban.com.au/guildford-clear-water-storage-tank
```

The transcript is written incrementally and flushed, so interrupted runs keep
messages already recorded. Each invocation gets a separate file; `--output-dir`
does not relocate it, and `--log-file` still selects only the JSONL decision log.
A transcript open/write/close error returns nonzero and restores terminal streams;
a broken log stops further processing without repeatedly trying to log its error.
Default database-output mode creates no text transcript.

| Output | Contents |
| --- | --- |
| `output/raw/<index-folder>/<article>.txt` | Exact normalized extractor text, saved before Claude. |
| `<output-dir>/<index>.txt` | Validated opportunity JSON array. |
| `output/logs/<run-id>.txt` | Terminal progress/errors, including Claude starts and validation failures; no added prompts, article bodies or raw response dumps. |
| `output/logs/scraper.jsonl` | Structured article history decisions, separate from the terminal transcript. |

Collection appends article decisions to `output/logs/scraper.jsonl`, resolved
relative to the project root. Override it with `main.py --log-file PATH`.
The JSONL events stay out of terminal PASS/FAIL output and JSON-array `.txt`
files. Each event includes its run, UTC timestamp, index, original/canonical
source URL and decision: `new`, `changed`, `unchanged`, `deleted`, `failed` or
`saved`, `refresh`, `structured` or `location`. Hash comparisons include previous/current hashes where available.
Location events include outcomes, provider/dataset identifiers and up to 400 characters
of supporting source evidence. The JSONL log excludes exception details, full
article bodies and credentials. A
JSONL file failure stops processing rather than redirecting events to the console.

`new`, `changed` and `refresh` mean eligible for Claude, not successfully processed.
`structured` records the attempt's date, source website index ID, geography warning
status and catalogue (`database` or `fixtures`); it does not claim persistence.
Text/fixture runs include these diagnostics without writing database history.
Fixture index IDs belong to their historical manifest, not the current database
catalogue.
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

## Verified affected locations

The single Claude response includes internal `geographicScope` evidence alongside
metadata. It never supplies coordinates or final geometry. Python checks exact
source excerpts, geographic roles and explicit state qualifiers, then resolves
unambiguous matches through the [Geoscience Australia gazetteer](https://services.ga.gov.au/gis/rest/services/Composite_Gazetteer_of_Australia/MapServer/0)
for representative place points or [ABS ASGS 2026 geographic services](https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-4-july-2026-june-2031/access-and-downloads/geospatial-web-services)
for locality, local-government and state boundaries. Lookups request WGS84 GeoJSON,
have a 20-second timeout and one HTTP retry, and use no cache. There is no second
Claude call or model-generated geometry.

Location means the area affected, independently of jurisdiction. Offices, contact
addresses, venues and incidental mentions do not become locations. Ambiguous
matches and unsupported representations produce no map. A representative place
point is labelled accordingly; a specific site is not substituted with its town
or an area's centroid. Exact sites, national boundaries and other source-specific
geography need supplied verified candidates. Version one does not fetch arbitrary
linked GIS files or convert shapefiles, screenshots or projected source data.
`LocationResolver(supplied=...)` accepts trusted candidates from code before API
lookup; they are not accepted from Claude. `compose_indexes(location_resolver=...)`
and `structure_listing(location_resolver=...)` allow injection for controlled use.

Python copies verified geometry and uses Pydantic plus Shapely to reject invalid
coordinates, nesting, empty geometry, unclosed rings and invalid topology. Polygon
holes and separate MultiPolygon areas are preserved unchanged, with no repairs,
centroid substitution or simplification. Multiple points and mixed point/area
sets cannot be exported as a single location. Separate verified areas can form a
MultiPolygon only when their combination is valid; an unresolved affected area
prevents exporting a misleading partial map.

A successful no-location determination writes SQL NULL and omits the location
property in exported JSON, including deliberate removal of an older map. Lookup
outages, invalid source geometry and unsupported model evidence at the resolution
stage are nonblocking geography warnings: valid metadata is still saved and its
successful hash advances. New opportunities receive SQL NULL geography; on updates,
the writer retains the previous map when lookup failed. A successful no-location
decision remains distinct and can clear an old map. Metadata validation/API errors
and persistence failures still fail the article and preserve prior history.
Use `--refresh-locations` to retry geography later; there is no extra Claude call
or automatic geography-driven structuring retry. Diagnostics use file-only `location`
events; internal scope, provenance and excerpts do not enter public location JSON.

Refresh selected articles after geographic data or resolution rules change:

```bash
uv run python main.py --refresh-locations --index "Coliban Water"
```

This bypasses unchanged-text skipping and reprocesses the complete opportunity;
IDs remain stable, deleted URLs stay excluded and limits still apply. It uses the
same text-history hash and requires no schema change. `--text` still never advances
history. Ordinary `--fixtures` uses offline resolution with supplied candidates
only; absent candidates mean no map and never trigger geographic network access.
It still calls real Claude. Synthetic geographic test fixtures are not geographic
evidence for real articles and are not automatically attached during replay.

Run offline location and one-call regression checks with:

```bash
uv run python -m unittest tests.test_locations tests.test_deadline_precision tests.test_eligibility tests.test_extraction_run_log tests.test_fixtures.FixtureTests
```

The location contract is described in [LOCATIONS.md](docs/LOCATIONS.md). Its broader
website database-protocol changes remain separate from this location implementation.

## Opportunity validation and database mapping

The model follows the [ECHO opportunity contract](https://github.com/MCLWxMBI/website/blob/main/docs/contracts.md#opportunity)
and [persistence requirements](https://github.com/MCLWxMBI/website/blob/main/docs/future-plans.md#opportunity-persistence).
Claude returns minimally cleaned, ordered full-text paragraphs and a separate
20–30-word summary. Wording and detail are preserved in full text. The complete
extracted text is supplied to Claude with the index name and canonical URL.

Extraction permits a null deadline; accepted opportunities require a UTC timestamp
ending in `Z` and `submissionDeadlinePrecision` (`datetime` or `month`, default
`datetime`). A closing month such as September 2027 is stored as
`2027-09-01T00:00:00Z` with precision `month`: it represents the whole month,
not an exact closing instant. Opening dates within that month are allowed.
Models also accept `2027-09` and normalize it with month precision. Consumers
must use precision when displaying deadlines or deriving closed status.

Date-only deadlines use 23:59:59 in the source's local timezone; date-only openings
use 00:00:00. Victorian sources default to Australia/Melbourne, accounting for
daylight saving. Unknown timezone/locality remains unresolved. Opening months
alone remain null because only deadlines have a precision column. For eligible
opportunities, engagement phases, surveys and community panels qualify, including engagement underway and
successive phases of one program. Claude prefers explicit feedback deadlines,
but may infer a closing date or month from the whole article, timelines and phase
descriptions without requiring "submissions close" wording. The ending month of
a clearly stated engagement range may supply the deadline. Milestones are assessed
in context; unrelated project dates alone do not establish a feedback deadline.
Return null for excluded articles or without reasonably supported explicit or contextual timing.
Approximate wording stays in full text without invented months. Do not infer
coordinates. Mocked tests verify prompt delivery, validation and persistence
handling; they do not demonstrate how real Claude will interpret an article.

Eligibility is evaluated inside the same Claude prompt and structured-response
call, before timing inference. Routine satisfaction/service-interaction surveys,
benchmarking, competitions, awards and promotional entries are excluded.
Information-only flood maps, advice, FAQs and updates are excluded without an
open or upcoming participation opportunity. Closed/reviewing consultations are
excluded unless another phase is open or upcoming; an ongoing project or future
map publication does not reopen feedback. Genuine consultation on specific plans,
pricing submissions and flood-management proposals remains eligible, including
surveys with incentives. Environmental keywords or a water-sector publisher alone
are insufficient. Excluded responses use a null deadline and datetime precision,
so existing validation prevents persistence. Retry guidance preserves the exclusions.
Existing saved outputs and database rows are not automatically removed.

Run the deadline model, eligibility/prompt-handoff and mocked persistence checks without
Claude usage or database access:

```bash
uv run python -m unittest tests.test_deadline_precision tests.test_eligibility
```

The devcontainer development database is recreated from `sql/schema.sql` when
schema changes are applied, then seeded from `sql/seed_website_indexes.sql`.
The deadline precision column defaults to `datetime`; month-level values must
be normalized to the beginning of the month in UTC.

Each attempted article gets at most one Claude API call. Both application and SDK
retries are disabled, including for invalid responses and API failures. A later
invocation may try again because failures do not advance history. The model is
explicitly configured, with no hard-coded default.

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

For raw-export/history integration checks, use the existing devcontainer
`scraper` database with rolled-back fixture changes (no database reset, Claude
calls or persistent article/history modifications):

```bash
RAW_EXPORT_POSTGRES_TESTS=1 uv run python -m unittest tests.test_fixtures.RawExportTests
```

Sidebar and terminal-transcript regressions use the minimized PS28 fixture and
mocked Claude responses, with no browser, website, database or paid API calls:

```bash
uv run python -m unittest tests.test_extraction_run_log
```


Run the processing-metadata unit checks without API calls:

```bash
uv run python -m unittest tests.test_history_metadata tests.test_locations
```

Opt in to real persistence checks on the existing Compose `scraper` database:

```bash
HISTORY_METADATA_POSTGRES_TESTS=1 uv run python -m unittest tests.test_history_metadata
```

These checks use saved article text and mocked Claude/geographic services. They
read the actual seeded website IDs and roll back every test transaction. They do
not create databases, reset data, load `.env` or use a remote `DATABASE_URL`.
The database must already have the current `sql/schema.sql` and seed applied.
