# OSS landscape evaluation — what open-law uses, adopts, or rejects

**Date:** 2026-09 · **Scope:** choose the building blocks for scraping and
consolidating legislation from around the world, before scaling the
adapter set up. Verdicts below were checked against live endpoints and
license metadata in September 2026; re-verify before reversing one.

## Decision summary

| Candidate | License | Verdict |
|---|---|---|
| [juriscraper](https://github.com/freelawproject/juriscraper) | BSD-2-Clause | **Don't fork.** Consume for case law; contribute upstream |
| [CourtListener](https://www.courtlistener.com/) API | (data, free) | Future read-only source adapter candidate |
| [cobalt](https://pypi.org/project/cobalt/) (Laws.Africa) | LGPL-3.0-or-later | **Rejected as dependency** — license gate; see below |
| laws.africa REST API | (token, free tier) | Documented integration candidate, not implemented yet |
| memorious (OCCRP) | AGPL-3.0 | Rejected — license + heavier than needed |
| scrapy | BSD-3-Clause | Deferred — official APIs need no crawl framework |
| Playwright | Apache-2.0 | Deferred — no JS-only source among current adapters |
| legislation.gov.uk API | Open Government Licence v3 | **Used** (`uk` adapter) |
| e-Gov 法令API v2 | GoJ Standard Terms of Use | **Used** (`jp` adapter) |
| JLT database (japaneselawtranslation.go.jp) | PDL 1.0 + MoJ © | **Used** (`jlt` adapter; TMX bilingual download per law, search CSRF-gated → fetch-by-id only — powers orimono's `reference-eval.py` via the same statutes) |
| law.go.kr DRF Open API | KOGL (attribution) | **Used** (`kr` adapter, key-gated via `LAW_KR_OC`) |
| EU CELLAR | Decision 2011/833/EU | **Used** (`eu` adapter) |
| eCFR public API | US public domain (17 USC §105) | **Used** (`us` adapter; govinfo key-gated, uscode.house.gov bot-gated — eCFR is the key-free regulatory channel) |
| Justice Laws Website XML | Crown copyright (non-commercial reproduction) | **Used** (`ca` adapter; legacy search has no machine endpoint, fetch-by-code only) |

Per-country channel status across Asia (robots verdicts, bot walls,
dead channels): see the [Asia coverage map](asia-coverage.md).

## Why not fork juriscraper

Juriscraper is the mature Python scraper library for *case law*: it
gathers judicial opinions, oral arguments, and PACER data, and its
upstream explicitly welcomes new geographies (recent additions include
Canada, Mexico, Argentina, and the UK). Three reasons a fork is the
wrong move for open-law:

1. **Scope mismatch.** Juriscraper targets courts, not statutes. The
   legislation half of "the world's laws" has no counterpart inside it;
   forking would start us with zero of the code we actually need.
2. **Forking forfeits the best part.** Free Law Project runs upstream
   scrapers on their infrastructure and publishes the results via
   CourtListener (472 jurisdictions). A PR upstream gets our scraper
   hosted, monitored, and its data redistributed; a private fork gets
   none of that and inherits a permanent merge burden.
3. **It is an installable library.** `pip install juriscraper` and call
   its `Site` classes — open-law can depend on it (BSD-2-Clause is
   MIT-compatible) when case-law coverage is added, with zero fork.

## cobalt is kept at arm's length

Laws.Africa's cobalt is the nicest Python library for building Akoma
Ntoso documents, but it is **LGPL-3.0-or-later**, and this project's
license-compliance task runs `pip-licenses --partial-match --fail-on=GPL`
— which substring-matches LGPL and fails the build. Beyond tooling, the
practical need is already covered: legislation.gov.uk serves native
`data.akn` renditions, so we surface AKN URLs instead of generating AKN
ourselves. Revisit only if (a) the compliance policy changes to
explicitly allow LGPL dynamic linking, or (b) open-law must *emit* AKN
for sources that lack it.

## Dead and retired channels (observed 2026-09)

Verified dead while probing; recorded so nobody rebuilds on them:

- **e-Gov 法令API v1** — `elaws.e-gov.go.jp/api/1/*` redirects to
  `laws.e-gov.go.jp` and 404s. The v2 JSON API replaced it.
- **LexML Brasil OAI-PMH** — `www.lexml.gov.br/oai?verb=Identify`
  returns 404. Brazilian legislation needs a new channel before any
  `br` adapter is attempted.
- **eCFR human search UI** (`/search`) — robots.txt `Disallow`; the
  `/api/` tree is explicitly open, so the `us` adapter uses the API only.
- **govinfo api.data.gov without a key** — `DEMO_KEY` is rate-limited
  in probing (429s); usable only with a registered key, so the `us`
  adapter does not depend on it.
- **uscode.house.gov** — bot-gated / under maintenance during probing
  (2026-10); statutes stay out of scope until the channel stabilises.
- **Justice Laws legacy Search.aspx to machines** — returns the empty
  form, not results; the `ca` adapter fetches by act code instead.

## The chosen architecture follows from the verdicts

Because official APIs beat scraping for every source we adopted, the
adapter layer fetches **known machine endpoints** (`fetcher.fetch_text(
url, discover=False)`): robots.txt, budget, rate limiting, and caching
still apply, but no feed/API probing and no feed-switching. Per-source
politeness lives on the adapter class (`crawl_delay_seconds` mirrors
legislation.gov.uk's robots `Crawl-delay: 5`; `http_headers` carries
CELLAR's content negotiation). Adding a jurisdiction means one
`SourceAdapter` subclass plus one registry line — the OSS question is
answered per source, not once for the project.
