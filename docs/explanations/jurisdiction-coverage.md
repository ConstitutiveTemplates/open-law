# Jurisdiction coverage map — channel status per adapter and probe

**Probe date:** 2026-10-11 · **Method:** `robots.txt` + one endpoint probe
each, politely (single spaced requests, `open-law-probe/1.0` UA). Status
is evidence-based, not aspirational; re-probe before acting on a row.
The charter
([CHARTER.md](https://github.com/politeuma/open-law/blob/main/CHARTER.md))
governs every row: robots.txt is law, a 403 challenge means denied, and
an API that exists but is robots-disallowed stays off-limits. Asia rows
live in [asia-coverage.md](asia-coverage.md); this file covers the
adapters added after it (Germany, US states) plus the jp/kr re-probes.

## Status legend

Same marks as [asia-coverage.md](asia-coverage.md): ✅ shipped ·
🔑 needs a free registration/key · 🤖 bot-challenged — denied means
denied · 🚫 robots-disallowed · 🧩 SPA shell / no machine channel ·
📄 reachable but scrape-only/unverified · 🔌 unreachable · ❓ unprobed.

## Adapter coverage (probed 2026-10-11)

| Adapter | Endpoint | Probe date | Status | Robots / crawl-delay | Notes |
|---|---|---|---|---|---|
| `de` | `https://www.gesetze-im-internet.de/<dir>/index.html` + `Teilliste_<L>.html` | 2026-10-11 | ✅ | robots.txt 200 `User-agent: *` + empty `Disallow:` (= allow all); `crawl_delay_seconds = 2.0` (conservative, no Crawl-delay stated) | `bgb/index.html` 200 (~486 KB); `stgb/index.html` 200; per-law `xml.zip` 200 (BGB ~467 KB, single `BJNR…xml`); unknown folder 404 with a 236 B error page |
| `us-tx` | TCAS search `https://tcss.legis.texas.gov/api/TCASSearch/GetPage/1/ZZ/<q>` + file server `https://tcss.legis.texas.gov/resources/<CODE>/htm/<CODE>.<ch>.htm` | 2026-10-11 | ✅ | `statutes.capitol.texas.gov/robots.txt` 200 empty body (= allow all); `tcss.legis.texas.gov/robots.txt` 404 (absent = allowed); `crawl_delay_seconds = 2.0` | API + file-server base URLs reverse-engineered from the shipped Angular bundles (`TCASCore: https://tcss.legis.texas.gov/api/`); `BC.503.htm` 200 (~9 KB, CUBI ch. 503); search `biometric` returns BC.72/BC.503/BC.510 chapters; the `statutes.capitol.texas.gov/Docs/…` HTML routes are SPA shells (same ~251 KB shell for every path) — the adapter uses the API/file hosts directly |
| `jp` | v1 `https://laws.e-gov.go.jp/api/1/lawdata/<law_id>` (fetch) + v2 `/api/2/laws` (search) | 2026-10-11 | ✅ | `laws.e-gov.go.jp/robots.txt` answers 200 but serves the SPA HTML shell (no rules; `crawl_delay_seconds = 1.0`) | Re-probe result: **no registration needed** — v1 `lawdata` returns full Law XML key-free (Civil Code `129AC0000000089` 200, 1.8 MB; small repeal act 200; bogus id → `Result/Code=1` + empty `LawFullText`). The elsur key is only needed for the newer v2 document endpoints, which the adapter does not use. `fetch` now parses title/promulgation date from the v1 XML. |
| `kr` | `https://www.law.go.kr/DRF/lawSearch.do` | 2026-10-11 | 🔑 | robots.txt 200 `User-agent:*` / `Allow: /` + sitemap; `crawl_delay_seconds = 1.0` | Re-probe confirms key-gating: key-less `lawSearch.do` answers HTTP 200 with `<result>필수입력요소 검증에 실패하였습니다</result>` ("required-input verification failed"). Register at openapi.law.go.kr (OC id, bound to the caller's server IP) and set `LAW_KR_OC`. No free path was wired. |
| `us` (CA leginfo — not implemented) | `https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1798.100.` | 2026-10-11 | 🤖 | `leginfo…/robots.txt` 403 (5.5 KB Cloudflare "Just a moment…" page); section page 403 for both the probe UA and a browser UA | Cloudflare-challenged: section pages, the codes index, and robots.txt all 403. Charter: denied means denied. Documented only — no `us-ca` adapter. |
| IL ilga.gov — not implemented | `https://www.ilga.gov/robots.txt` | 2026-10-11 | 🔌 | Unreachable: connection timeout after 20 s from the probe network (TLS-reset class block from datacenters, as previously reported) | Wayback-only per the ticket: no live adapter. No fixture captured (nothing reachable to capture). |

## How to extend this map

Same probing protocol as
[asia-coverage.md](asia-coverage.md#how-to-extend-this-map): robots.txt
first, then one endpoint probe, spaced ≥2 s — record the HTTP code in
the table above. A new US state follows the `us-tx` pattern (static
file host + key-free JSON API behind the site's JS bundle) with source
id `us-<postal>`; a blocked site gets a table row here, not an
adapter.
