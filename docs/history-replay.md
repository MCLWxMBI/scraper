# Historical discovery replay

Run `./scripts/test_history_replay.sh` or select one exact index name with `--index`. The shell entry point works from another directory using its absolute path.

The runner compares recorded listing membership, feeds saved article bodies through production extraction and discovery history checks, and primes successful-history rows between stages in a temporary database on real devcontainer PostgreSQL. It never invokes Claude, performs browser discovery, or writes opportunities. Same-URL bodies are deliberately reused; historical content equality is not asserted.

All fixture checksums are checked, including repeated resource references. Listing entries must be supported by saved HTML links or embedded URLs. Existing files only: no archive downloads or live substitutes. Test history represents earlier successful processing; writer, deletion-trigger and transaction tests are separately available in `tests.test_article_history`.

## Comparison schedule

Capture IDs are UTC (`YYYYMMDDHHMMSS`). A timestamp without a saved usable resource remains an unavailable candidate, not replay evidence. “Partial” and “empty” are not a complete deduplication pass.

| ID | Index | Older capture | Newer capture | Coverage |
| --- | --- | --- | --- | --- |
| 1 | Legislative Assembly Environment and Planning Committee | 20251119213559 | 20260211115141 | partial: 0 shared ready; 1 ready additions |
| 2 | Legislative Council Environment and Planning Committee | 20251128084544 | 20260210195336 | passed: 1 shared ready; 1 ready additions |
| 3 | Scrutiny of Acts and Regulations Committee | — | 20260901032833 | Skipped: Missing usable older/newer listing file |
| 4 | Melbourne Water | — | 20260117154239 | Skipped: Missing usable older/newer listing file |
| 5 | Great Western Water | — | — | Skipped: Missing usable older/newer listing file |
| 6 | South East Water | 20260211125204 | 20260618080745 | Skipped: Missing usable older/newer listing file |
| 7 | Yarra Valley Water | 20251106211959 | 20251124151143 | Skipped: Missing usable older/newer listing file |
| 8 | Barwon Water | 20251123135332 | 20251127203310 | Skipped: No ready article bodies for these listings |
| 9 | Coliban Water | 20260505033327 | 20260508113946 | passed: 1 shared ready; 1 ready additions |
| 10 | East Gippsland Water | — | — | Skipped: Missing usable older/newer listing file |
| 11 | Goulburn Valley Water | — | 20260410144026 | Skipped: Missing usable older/newer listing file |
| 12 | Gippsland Water | 20260206200037 | 20260512161933 | partial: 2 shared ready; 0 ready additions; 1 additions without ready bodies |
| 13 | Grampians Wimmera Mallee Water - Current Projects | — | 20260712064057 | Skipped: Missing usable older/newer listing file |
| 14 | Grampians Wimmera Mallee Water - Past Projects | 20260710194154 | 20260711204826 | Skipped: Missing usable older/newer listing file |
| 15 | Lower Murray Water | — | — | Skipped: Missing usable older/newer listing file |
| 16 | North East Water | 20260216175709 | 20260608150334 | partial: 1 shared ready; 0 ready additions; 4 additions without ready bodies |
| 17 | South Gippsland Water | — | 20260611064417 | Skipped: Missing usable older/newer listing file |
| 18 | Wannon Water | 20260313135317 | 20260615043943 | partial: 1 shared ready; 0 ready additions; 3 additions without ready bodies |
| 19 | Western Port Water | 20260325212128 | 20260421012845 | Skipped: Missing usable older/newer listing file |
| 20 | Southern Rural Water | 20260414113428 | 20260614032742 | partial: 2 shared ready; 0 ready additions |
| 21 | Goulburn-Murray Water | 20251107140958 | 20260412124944 | partial: 0 shared ready; 2 ready additions; 4 additions without ready bodies |
| 22 | Essential Services Commission | 20260207015404 | 20260617072451 | partial: 0 shared ready; 2 ready additions; 1 additions without ready bodies |
| 23 | Commissioner for Environmental Sustainability Victoria | 20251125091251 | 20251205032038 | partial: 2 shared ready; 0 ready additions; 1 additions without ready bodies |
| 24 | Vic Catchments | 20260119135259 | 20260419013113 | partial: 1 shared ready; 0 ready additions |
| 25 | Victorian Environmental Water Holder | 20251124193527 | 20251220105836 | partial: 1 shared ready; 0 ready additions |
| 26 | Engage Victoria | 20260630062035 | 20261001022315 | Skipped: No ready article bodies for these listings |
| 27 | Senate Environment and Communications | 20260507025227 | 20260804060123 | partial: 1 shared ready; 0 ready additions; 5 additions without ready bodies |
| 28 | Senate Rural and Regional Affairs and Transport | 20260122164753 | 20260423024735 | partial: 1 shared ready; 0 ready additions; 1 additions without ready bodies |
| 29 | House Climate Change, Energy, Environment and Water | 20260331023521 | 20260510084900 | Skipped: Missing usable older/newer listing file |
| 30 | House Industry, Innovation and Science | 20260215211800 | 20260322215629 | Skipped: Missing usable older/newer listing file |
| 31 | House Regional Development, Infrastructure and Transport | 20260505052100 | 20260518101405 | partial: 1 shared ready; 0 ready additions |
| 32 | House Primary Industries | 20260305231908 | 20260618005400 | partial: 1 shared ready; 0 ready additions |
| 33 | Joint Aboriginal and Torres Strait Islander Affairs | 20260226162001 | 20260507010819 | Skipped: No ready article bodies for these listings |
| 34 | Joint Treaties | 20251115214232 | 20251126065001 | partial: 1 shared ready; 0 ready additions; 1 additions without ready bodies |
| 35 | Joint Northern Australia | 20260114233433 | 20260308040406 | Skipped: Missing usable older/newer listing file |
| 36 | Department of Industry, Science and Resources | — | 20260615111550 | Skipped: Missing usable older/newer listing file |
| 37 | Productivity Commission | — | — | Skipped: Missing usable older/newer listing file |
| 38 | Climate Change Authority | — | — | Skipped: Missing usable older/newer listing file |
| 39 | Australian Energy Market Commission | 20251101033227 | 20260101033231 | partial: 1 shared ready; 0 ready additions |
| 40 | Department of Climate Change, Energy, the Environment and Water | — | — | Skipped: Missing usable older/newer listing file |
| 41 | Clean Energy Regulator | 20260710164505 | 20260924143419 | Empty open-consultation states; no deduplication claim |
| 42 | Department of Infrastructure, Transport, Regional Development, Communications, Sport and the Arts | 20251112004508 | 20251115093747 | passed: 1 shared ready; 2 ready additions |

Gippsland future projects are kept as a separate comparison: `20251206125753` → `20260411024308`. No ready selected article body supports that section pair, so it is reported as skipped. Sections captured at different times are not presented as an atomic historical snapshot.

The Assembly’s saved entries replace `regionalhousing` with `apartmentrenewables`, contrary to the report’s same-item description. The runner follows the saved evidence and marks this pair partial because it has no shared URL. Wannon’s sample is a shared-body history check, not a claim that its saved completed project is currently eligible. Vic Catchments and VEWH use stable inline/document source identities rather than independent card URLs. Treaty and VEWH samples preserve their existing local PDF extraction routes.

## Results and limits

Validation on the devcontainer PostgreSQL service checked 116 resources and all 42 main index cases, plus Gippsland’s separate future section: three complete sampled comparisons, 16 partial comparisons, one explicit empty-state comparison and 23 skipped section/index cases. Across replay stages, 29 new candidates passed the history gate and 47 unchanged candidates skipped processing. The temporary database was dropped.

These counts describe the bundled sample coverage, not every historical article or future discovery stability. Missing article bodies cannot verify new-article processing. No order-based early stopping is added. The runner selects up to two shared ready articles, two ready additions and, where available, two older-only articles, preserving listing order.

For trigger, deletion, rollback, changed-content and file-log verification using the same saved fixtures and actual PostgreSQL, run:

```bash
ARTICLE_HISTORY_INTEGRATION=1 uv run python -m unittest tests.test_article_history
```

Those automated collection integration checks mock Claude responses; the discovery replay itself never reaches the Claude layer. Normal `main.py --fixtures` continues to call real Claude and incurs usage.
