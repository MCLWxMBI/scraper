# Historical article fixtures

This collection supports `python main.py --fixtures` and offline regression
tests. CLI replay starts from the manifest's saved article samples, not from
listing discovery. It calls **real Claude**, needs `ANTHROPIC_API_KEY` and
`CLAUDE_MODEL`, and incurs API usage. It writes JSON-array text files under
`output/fixtures/` by default and does not use PostgreSQL or a browser.

```bash
uv run python main.py --fixtures --index "Coliban Water" --limit 1
```

Tests mock Claude and never refresh the data or make external requests.

## Provenance and selection

The starting listings are the inspected snapshots linked in
[the stability report](../../../docs/stability_report.md), including relevant
downstream pages and the inspected CES second page. Successful re-downloads
are kept as HTML; original audit listing entries remain available even when a
replay subsequently failed. Those entries describe audit observations, not a
claim that a newly downloaded page was rendered completely.

Up to three distinct article URLs per seed index are sampled, prioritizing
newly appearing links and shared links, then another available example. The
manifest covers all 42 seed IDs, including inactive entries. Only article
entries marked `ready` are supplied to the CLI. Article sampling does not
reapply the live discovery eligibility filters; historical closed inquiries
and projects can intentionally exercise validation behavior.

Article bodies were collected additionally to the listing audit. For each
article URL, successful CDX captures were selected nearest its referencing
listing timestamp within 21 October 2025–21 October 2026, with earlier captures
preferred on equal distance. The actual replay timestamp may differ from the
requested timestamp and is recorded. Separately captured pages and PDFs are
not an atomic historical website state. Listing appearances do not prove
publication dates.

Downloads used archive-only redirects, a shared minimum two-second request
spacing and at most one retry per request. Failed captures and missing dynamic
content were not repaired with live websites. No Claude calls were used to
build this collection.

## Manifest and files

`manifest.json` has `version: 1` and an `indexes` array. Each index records its
seed identity, activation flag, coverage reason, listings and articles.

- Listings record their route, requested timestamp, ordered audit entries and
  either a saved resource or an unavailability reason. Entries retain URL,
  title, section and explicit dates/context from the audit. These can be used
  for future ordering and URL-membership tests.
- Articles record the original `source_url`, extractor `source_name`, route,
  referring listing, HTML resource, any PDF resources, and `ready` or
  `unavailable` status. A failed sample can retain its successfully saved HTML
  even when its required PDF is unavailable.
- Resources record the original URL, requested and actual capture timestamps,
  replay URL, content type, relative path and SHA-256 checksum. Paths are
  relative to this directory and grouped by two-digit seed ID. Filename hashes
  identify the original downloads and remain unchanged. Manifest checksums verify
  the exact stored bytes: downloaded, decompressed HTML normalized to LF line
  endings, and unmodified PDF bytes. Git attributes preserve these bytes across
  checkouts regardless of `core.autocrlf`.

HTML is archived source content, not a browser-rendered DOM. Embedded listing
data is retained inside the original HTML; scripts and external assets are
never executed. PDFs preserve the downloaded PDF bytes. Missing archive content
is represented by coverage metadata rather than fabricated article bodies.

The local adapter feeds saved HTML through existing HTML extraction and feeds
manifest-listed PDF bytes through the existing special PDF selectors/parser.
No missing resource can trigger an HTTP request. Relative paths and symlinks
must resolve inside the collection directory; selected resource checksums are
verified before extraction. Original URLs, rather than local filenames or
Wayback URLs, go to Claude and determine opportunity identities.

## Extending and reviewing fixtures

1. Choose an archived listing/article and record its original URL and actual
   capture timestamp. Preserve a link to the referring listing.
2. Download only archived HTML and required PDFs. Normalize HTML CRLF line
   endings to LF before calculating SHA-256 checksums; preserve PDF bytes exactly.
   Keep content and provenance intact and add resource descriptors. Never include
   credentials, authenticated sessions or generated Claude responses.
3. Review the saved body, extraction route and any expected text fragments
   against the source. Keep extractor limitations explicit; do not invent
   deadlines, categories or other model-produced metadata.
4. Add or update the relevant manifest sample, preserving the three-article
   maximum and all 42 seed entries. Mark incomplete samples `unavailable`
   with a concrete reason. Do not silently remove gaps.
5. Run `uv run python -m unittest tests.test_fixtures`. Existing synthetic
   parser, pipeline and structuring tests remain independent of archive access.

The fixture CLI preserves normal validation and output semantics. It may
reject a saved article for a missing deadline, ambiguous URL or invalid Claude
response. A saved file is test input, not a guarantee of a valid opportunity.
Repeated fixture runs deliberately call Claude again; processing history is
outside this feature.

## Collected coverage

All 42 seed indexes are represented; 30 have usable samples, totaling 50 articles. Two saved PDFs cover VEWH and Joint Treaties. SARC has no captured bill rows from which to select an article; its PDF route is covered by synthetic adapter tests.

Engage retains its archived HTML and embedded Inertia data as reference, but it is unavailable for article replay because the current static HTML extractor cannot render that data. Other gaps include missing captures, connection failures and genuinely empty listings. Exact failed-sample reasons are in the manifest.

| Seed ID | Index | Ready articles | Saved listings |
| --- | --- | --- | --- |
| 1 | Legislative Assembly Environment and Planning Committee | 2 | 2 |
| 2 | Legislative Council Environment and Planning Committee | 2 | 3 |
| 3 | Scrutiny of Acts and Regulations Committee | 0 | 1 |
| 4 | Melbourne Water | 2 | 1 |
| 5 | Great Western Water | 0 | 0 |
| 6 | South East Water | 3 | 1 |
| 7 | Yarra Valley Water | 2 | 1 |
| 8 | Barwon Water | 0 | 2 |
| 9 | Coliban Water | 2 | 2 |
| 10 | East Gippsland Water | 0 | 0 |
| 11 | Goulburn Valley Water | 2 | 0 |
| 12 | Gippsland Water | 2 | 4 |
| 13 | Grampians Wimmera Mallee Water - Current Projects | 2 | 1 |
| 14 | Grampians Wimmera Mallee Water - Past Projects | 3 | 1 |
| 15 | Lower Murray Water | 0 | 0 |
| 16 | North East Water | 1 | 2 |
| 17 | South Gippsland Water | 1 | 1 |
| 18 | Wannon Water | 1 | 2 |
| 19 | Western Port Water | 3 | 2 |
| 20 | Southern Rural Water | 2 | 2 |
| 21 | Goulburn-Murray Water | 2 | 3 |
| 22 | Essential Services Commission | 2 | 2 |
| 23 | Commissioner for Environmental Sustainability Victoria | 2 | 5 |
| 24 | Vic Catchments | 1 | 2 |
| 25 | Victorian Environmental Water Holder | 1 | 2 |
| 26 | Engage Victoria | 0 | 2 |
| 27 | Senate Environment and Communications | 1 | 2 |
| 28 | Senate Rural and Regional Affairs and Transport | 1 | 2 |
| 29 | House Climate Change, Energy, Environment and Water | 1 | 1 |
| 30 | House Industry, Innovation and Science | 1 | 1 |
| 31 | House Regional Development, Infrastructure and Transport | 1 | 2 |
| 32 | House Primary Industries | 1 | 2 |
| 33 | Joint Aboriginal and Torres Strait Islander Affairs | 0 | 2 |
| 34 | Joint Treaties | 1 | 2 |
| 35 | Joint Northern Australia | 1 | 1 |
| 36 | Department of Industry, Science and Resources | 0 | 0 |
| 37 | Productivity Commission | 0 | 0 |
| 38 | Climate Change Authority | 0 | 0 |
| 39 | Australian Energy Market Commission | 1 | 2 |
| 40 | Department of Climate Change, Energy, the Environment and Water | 0 | 0 |
| 41 | Clean Energy Regulator | 0 | 3 |
| 42 | Department of Infrastructure, Transport, Regional Development, Communications, Sport and the Arts | 3 | 2 |
