# Source notes: opportunity index ordering

Observed using Playwright on 6 October 2026. Inspected all 42 supplied URLs,
including intermediate project hubs and up to two pagination/load-more states
per listing. These observations establish current ordering, not stability across
runs. Of the 42 URLs, 39 were reachable; Barwon Water, VEWH and AEMC returned
HTTP 403. The reachable GWMWater past-projects page remains intentionally skipped.

| Index | Observed ordering | Implication for a previously collected article floor |
| --- | --- | --- |
| [SARC bills](https://www.legislation.vic.gov.au/bills/in-parliament) and [Joint Treaties](https://www.aph.gov.au/Parliamentary_Business/Committees/Joint/Treaties) | Titles appear alphabetically, with years/referral dates mixed. | A new item can appear anywhere. Scan the complete list. |
| [East Gippsland Water](https://egwater.vic.gov.au/community/news) | Sampled publication dates descend, but the first article is explicitly **Featured**. | A known featured article must not stop discovery of newer articles below it. |
| [CES news](https://www.ces.vic.gov.au/news) | Publication dates descend across both sampled pages. | Strongest candidate for a chronological cutoff, subject to checking ties and future ordering changes. |
| [Coliban Water](https://connect.coliban.com.au/projects) | Sampled cards descend by **last updated**, with several same-day ties. | Potential optimisation, but updates to existing projects can move them. This is not publication order. |
| [Yarra Valley Water](https://engage.yvw.com.au/projects), [Lower Murray Water](https://yoursay.lmw.vic.gov.au/projects) | Update dates are not chronological. Yarra Valley shows **17 July → 1 June → 10 August**. | A recent item can sit below older known items. |
| [Infrastructure consultations](https://www.infrastructure.gov.au/have-your-say) | Open section explicitly defaults to **Open date, descending**. | A possible section-specific cutoff; opening date still differs from article publication date. |
| [Engage Victoria](https://engage.vic.gov.au/project) | Open and closed cards are mixed; page two still contains open items. No publication-order guarantee was exposed. | Scan eligible pages rather than treating the first known card as a boundary. |
| Gippsland/Western Port; Industry/CCA/DCCEEW | Separate current/future or open/pending lists. | Each section needs independent discovery. A match in one must not stop another. |
| Remaining project collections, including [Vic Catchments](https://viccatchments.com.au/priority-projects) | Mostly curated cards or descriptions on stable URLs, without verified publication ordering. | URL history works for new links; detecting new content on existing pages needs refresh/change detection. |
