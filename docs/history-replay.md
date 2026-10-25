# Historical discovery replay

Run `./scripts/test_history_replay.sh` or select an exact index name with `--index`. The shell entry point also works when invoked by absolute path from another directory.

The runner uses the real local devcontainer `scraper` database directly. It creates no separate databases. It applies/verifies the schema and 41-index seed, then checks actual opportunity/hash persistence, failed-write rollback, changed hashes and physical deletion/tombstone protection. Test article and history rows are cleared before and after checks, including failure cleanup. Seeded indexes remain intact.

Older/newer stages feed recorded listing membership into production discovery preparation and prime real history rows to represent previous successful processing. Claude is never invoked. Shared URLs reuse the same saved article body, so historical content equality is not asserted. This is a history-gate regression check, not a complete browser-pagination replay.

## Comparison schedule

Capture IDs are UTC (`YYYYMMDDHHMMSS`). Unavailable captures are recorded candidates, not successful replay evidence. Complete sampled comparisons require both shared ready articles and ready additions. Partial/empty/skipped cases are explicitly separate.

| ID | Index | Older capture | Newer capture | Coverage |
| --- | --- | --- | --- | --- |
| 1 | Legislative Assembly Environment and Planning Committee | 20251119213559 | 20260211115141 | partial: 0 shared ready; 1 ready additions |
| 2 | Legislative Council Environment and Planning Committee | 20251128084544 | 20260210195336 | passed: 1 shared ready; 1 ready additions |
| 3 | Scrutiny of Acts and Regulations Committee | — | 20260901032833 | skipped: Missing usable older/newer listing file |
| 4 | Melbourne Water | — | 20260117154239 | skipped: Missing usable older/newer listing file |
| 5 | Great Western Water | — | — | skipped: Missing usable older/newer listing file |
| 6 | South East Water | 20260211125204 | 20260618080745 | skipped: Missing usable older/newer listing file |
| 7 | Yarra Valley Water | 20251106211959 | 20251124151143 | skipped: Missing usable older/newer listing file |
| 8 | Barwon Water | 20251123135332 | 20251127203310 | skipped: No ready article bodies for these listings |
| 9 | Coliban Water | 20260505033327 | 20260508113946 | passed: 1 shared ready; 1 ready additions |
| 10 | East Gippsland Water | — | — | skipped: Missing usable older/newer listing file |
| 11 | Goulburn Valley Water | — | 20260410144026 | skipped: Missing usable older/newer listing file |
| 12 | Gippsland Water | 20251206125753 | 20260411024308 | partial: 1 shared ready; 0 ready additions |
| 13 | Grampians Wimmera Mallee Water - Current Projects | — | 20260712064057 | skipped: Missing usable older/newer listing file |
| 14 | Lower Murray Water | — | — | skipped: Missing usable older/newer listing file |
| 15 | North East Water | 20260216175709 | 20260608150334 | partial: 1 shared ready; 0 ready additions; 4 additions without ready bodies |
| 16 | South Gippsland Water | — | 20260611064417 | skipped: Missing usable older/newer listing file |
| 17 | Wannon Water | 20260313135317 | 20260615043943 | partial: 1 shared ready; 0 ready additions |
| 18 | Western Port Water | 20251205112732 | 20251211032411 | partial: 2 shared ready; 0 ready additions |
| 19 | Southern Rural Water | 20260414113428 | 20260614032742 | partial: 2 shared ready; 0 ready additions |
| 20 | Goulburn-Murray Water | 20251107140958 | 20260412124944 | partial: 0 shared ready; 2 ready additions; 4 additions without ready bodies |
| 21 | Essential Services Commission | 20260207015404 | 20260617072451 | partial: 0 shared ready; 2 ready additions; 1 additions without ready bodies |
| 22 | Commissioner for Environmental Sustainability Victoria | 20251125091251 | 20251205032038 | partial: 2 shared ready; 0 ready additions; 1 additions without ready bodies |
| 23 | Vic Catchments | 20260119135259 | 20260419013113 | partial: 1 shared ready; 0 ready additions |
| 24 | Victorian Environmental Water Holder | 20251124193527 | 20251220105836 | partial: 1 shared ready; 0 ready additions |
| 25 | Engage Victoria | 20260630062035 | 20261001022315 | skipped: No ready article bodies for these listings |
| 26 | Senate Environment and Communications | 20260507025227 | 20260804060123 | partial: 1 shared ready; 0 ready additions; 5 additions without ready bodies |
| 27 | Senate Rural and Regional Affairs and Transport | 20260122164753 | 20260423024735 | partial: 1 shared ready; 0 ready additions; 1 additions without ready bodies |
| 28 | House Climate Change, Energy, Environment and Water | 20260331023521 | 20260510084900 | skipped: Missing usable older/newer listing file |
| 29 | House Industry, Innovation and Science | 20260215211800 | 20260322215629 | skipped: Missing usable older/newer listing file |
| 30 | House Regional Development, Infrastructure and Transport | 20260505052100 | 20260518101405 | partial: 1 shared ready; 0 ready additions |
| 31 | House Primary Industries | 20260305231908 | 20260618005400 | partial: 1 shared ready; 0 ready additions |
| 32 | Joint Aboriginal and Torres Strait Islander Affairs | 20260226162001 | 20260507010819 | skipped: No ready article bodies for these listings |
| 33 | Joint Treaties | 20251115214232 | 20251126065001 | partial: 1 shared ready; 0 ready additions; 1 additions without ready bodies |
| 34 | Joint Northern Australia | 20260114233433 | 20260308040406 | skipped: Missing usable older/newer listing file |
| 35 | Department of Industry, Science and Resources | — | 20260615111550 | skipped: Missing usable older/newer listing file |
| 36 | Productivity Commission | — | — | skipped: Missing usable older/newer listing file |
| 37 | Climate Change Authority | — | — | skipped: Missing usable older/newer listing file |
| 38 | Australian Energy Market Commission | 20251101033227 | 20260101033231 | partial: 1 shared ready; 0 ready additions |
| 39 | Department of Climate Change, Energy, the Environment and Water | — | — | skipped: Missing usable older/newer listing file |
| 40 | Clean Energy Regulator | 20260710164505 | 20260924143419 | empty: Explicit empty open-consultation states; no deduplication claim |
| 41 | Department of Infrastructure, Transport, Regional Development, Communications, Sport and the Arts | 20251112004508 | 20251115093747 | passed: 1 shared ready; 2 ready additions |

## Changed project scopes

- **Gippsland (12):** only future-project snapshots from December 2025 and April 2026. One shared project survives while two older projects leave the list. All three future-project article samples are saved; no newly arriving URL appears in this pair. Current-project captures and the obsolete second section case were removed.
- **Wannon (17):** the existing March/June HTML was captured from the unfiltered listing. Both contain an explicit In planning card for Quality Water for Wannon. Manifest entries are selected from these real labels using the production card-status rule, with `selection.from_unfiltered_archive=true`. URLs and bytes remain those of the actual unfiltered captures. The corresponding saved article is from 15 May 2026. Completed/in-progress samples are excluded. No filtered Wayback snapshot is claimed.
- **Western Port (18):** 5/11 December current-project listings share the same four identities. Two ready article samples exercise unchanged skipping, not new arrivals. Next Generation was recovered from March 2026; the saved June water-main article is reused with its verified canonical URL. Other attempted listing/article replays were rate-limited and remain unavailable.
- **GWMWater past projects:** removed entirely; subsequent IDs and fixture directories were renumbered. The original stability report remains a dated account of the previous 42-index catalogue, not the current replay schedule.

The Assembly’s saved entries replace regionalhousing with apartmentrenewables, differing from the original report wording. It is an arrival/replacement case without a shared URL. Vic Catchments and VEWH retain stable inline/document identities; VEWH and Joint Treaties preserve local PDF extraction.

## Validation results

The replay passed on devcontainer PostgreSQL 18.6 directly in `scraper`: all 111 resource checksums and 41 index cases were checked. There are three complete sampled comparisons, 17 partial comparisons, one explicit empty-state case and 20 skipped cases. Across the stages, 32 new candidates passed the history gate and 49 unchanged candidates skipped processing. Five database checks passed. Test opportunities and history were cleared afterward.

Limits remain explicit: missing article bodies cannot verify their processing, unchanged samples do not guarantee future ordering, and independently captured listings/articles are not an atomic historical view. At most two shared ready samples, two additions and two older-only samples are selected per index while preserving listing order.

Fixture refresh uses Wayback only, LF-normalized HTML, preserved PDF bytes, paced requests and bounded retries. Normal regression/replay tests perform no website/Wayback requests. Ordinary `main.py --fixtures` still calls real Claude and incurs usage.

```bash
uv run python -m unittest tests.test_fixtures
./scripts/test_history_replay.sh
```
