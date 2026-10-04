# Asia coverage map — channel status per jurisdiction

**Probe date:** 2026-09 · **Method:** robots.txt + endpoint probes from
this network, politely (single requests, spaced). Status is evidence-based,
not aspirational; re-probe before acting on a row. The charter
([CHARTER.md](https://github.com/kasi-x/open-law/blob/main/CHARTER.md)) governs every row: robots.txt is law,
a 403 challenge means denied, and an API that exists but is
robots-disallowed stays off-limits.

## Status legend

| Mark | Meaning |
|---|---|
| ✅ | Adapter shipped and tested (offline fixtures, live-verified where noted) |
| 🔑 | Adapter shipped; needs a free registration/key in the environment |
| 🤖 | Bot-challenged (403/Cloudflare-style) — denied means denied |
| 🚫 | robots.txt disallows programmatic access to the content paths |
| 🧩 | SPA shell / no machine channel; API off-limits or absent |
| 📄 | Plainly reachable, scrape-only or unverified machine channel |
| 🔌 | Unreachable from the probe network (DNS / timeout / 503) |
| ❓ | Not yet probed |

## East Asia

| Jurisdiction | Channel | Status | Evidence / next step |
|---|---|---|---|
| Japan 🇯🇵 | e-Gov 法令API v2 (laws.e-gov.go.jp) | ✅ | `jp` adapter; open JSON law list, full text needs 利用者登録 |
| South Korea 🇰🇷 | law.go.kr DRF Open API | 🔑 | `kr` adapter; robots `Allow: /` (verified); needs `LAW_KR_OC` from openapi.law.go.kr (IP-bound registration) |
| China 🇨🇳 | flk.npc.gov.cn 国家法律法规数据库 | 🧩 | No public API known; JS-heavy portal — not probed in 2026-09 |
| Taiwan 🇹🇼 | law.moj.gov.tw 全國法規資料庫 | 🚫 | robots.txt `Disallow: /` for all agents (verified 2026-09); their Open API rides the same host |
| Hong Kong 🇭🇰 | elegislation.gov.hk (HKeL) | 🚫 | robots allows `/` and `/sitemap` only (verified); an official API on a separate host would change this |
| Mongolia 🇲🇳 | legalinfo.mn | 🧩 | `/api/` answers 403 and the law list is a JS-rendered shell (verified 2026-09) — no charter-compatible channel |
| Macau 🇲🇴 | bo.io.gov.mo (Official Gazette) | 🔌 | DNS does not resolve from the probe network (verified 2026-09) |

## Southeast Asia

| Jurisdiction | Channel | Status | Evidence / next step |
|---|---|---|---|
| Singapore 🇸🇬 | sso.agc.gov.sg | 🤖 | CloudFront 403 on robots.txt itself (verified); official API exists on request — contact AGC first |
| Vietnam 🇻🇳 | vbpl.vn | 🤖 | 403 challenge page (verified) |
| Thailand 🇹🇭 | Ratchakitcha Royal Gazette API | 🔑 | Official API with key (not probed 2026-09) — the natural `th` adapter |
| Indonesia 🇮🇩 | peraturan.bpk.go.id (national DB) | 🤖 | robots allows content, but Detail pages answer 403 (verified) — WAF; robots Disallow: /api/ elsewhere |
| Indonesia 🇮🇩 | peraturan.go.id / JDIH | 📄 | No robots.txt (verified); content channel unverified |
| Malaysia 🇲🇾 | lom.agc.gov.my | 📄 | Portal up (verified); robots.txt itself 500s; act tables are JS DataTables and documents ship through tokenized `processFile.php` |
| Philippines 🇵🇭 | Official Gazette / SC eLibrary | 📄 | Unverified |
| Cambodia 🇰🇭 | code.cambodia.gov.kh | 🔌 | DNS does not resolve from the probe network (verified 2026-09); robots.txt had been absent earlier |
| Laos 🇱🇦 | laoofficialgazette.gov.la | ✅ | `la` adapter; server-rendered display pages with Lao-labeled metadata rows and PDF full text (fetched live 2026-09); id-addressed via the site/list pages |
| Myanmar 🇲🇲 | mola.gov.mm | 🔌 | Homepage connection timeout (verified 2026-09); robots.txt absent where reachable |
| Brunei 🇧🇳 | agc.gov.bn | 📄 | robots.txt 404 (verified); content channel unverified |
| Timor-Leste 🇹🇱 | mj.gov.tl | 📄 | Standard Drupal robots.txt with `Crawl-delay: 10`, only internal dirs disallowed (verified); the ministry portal is small — actual legislation lives in the Journal da República, whose URL pattern still needs mapping |

## South Asia

| Jurisdiction | Channel | Status | Evidence / next step |
|---|---|---|---|
| India 🇮🇳 | indiacode.nic.in | 📄 | Reachable, but `/server/api` + `/rest` 404 (verified) — no REST; data.gov.in datasets (free key) are the machine channel |
| Bangladesh 🇧🇩 | bdlaws.minlaw.gov.bd | ✅ | `bd` adapter; no robots.txt, server-rendered UTF-16 HTML (fetched live 2026-09); id-addressed — the chronological index is JS-rendered |
| Nepal 🇳🇵 | lawcommission.gov.np | ✅ | `np` adapter; robots `Crawl-delay: 10` mirrored, server-rendered `/content/<id>/` pages (fetched live 2026-09); discovery via `/category/<id>` indexes |
| Pakistan 🇵🇰 | web.molaw.gov.pk | 🔌 | DNS does not resolve from the probe network (verified 2026-09) |
| Sri Lanka 🇱🇰 | lawnet.gov.lk | 🚫 | TLS certificate hostname mismatch (verified) — fetching would require disabling verification, which the charter refuses |
| Bhutan 🇧🇹 | ol.gov.bt | 🔌 | DNS does not resolve from the probe network (verified 2026-09) |
| Maldives 🇲🇻 | agoffice.gov.mv | 📄 | robots.txt `Disallow:` (empty = allow all, verified); content unverified |
| Afghanistan 🇦🇫 | moj.gov.af | 📄 | Real robots.txt present, header-only sampled (verified); content channel unverified |

## Central Asia & Caucasus

| Jurisdiction | Channel | Status | Evidence / next step |
|---|---|---|---|
| Kazakhstan 🇰🇿 | adilet.zan.kz | 🧩 | robots welcomes polite bots and allows act pages + the sitemap index, but `Disallow: /api/` and act pages are a JS-rendered SPA shell (verified); the sitemap gateway itself answered 504 on retry (verified 2026-09) |
| Uzbekistan 🇺🇿 | lex.uz | 📄 | No robots.txt (verified); a JSON `/api/` router exists but endpoint names are undocumented — probe `/api/<resource>` before writing an adapter |
| Kyrgyzstan 🇰🇬 | cbd.minjust.gov.kg | 🤖 | WAF answers "Forbidden" on robots.txt itself (verified) |
| Tajikistan 🇹🇯 | adlia.tj | 🔌 | 503 Service Unavailable (verified 2026-09) |
| Turkmenistan 🇹🇲 | minjust.gov.tm | 🧩 | robots.txt served as an HTML page (verified); site is JS-heavy |
| Georgia 🇬🇪 | matsne.gov.ge | 🤖 | "Access Denied" page on robots.txt (verified) |
| Armenia 🇦🇲 | arlis.am | 🧩 | No robots.txt and a 1.4 MB JS-app homepage with no crawler-visible act links (verified) |
| Azerbaijan 🇦🇿 | e-qanun.az | 🧩 | Next.js app; no robots.txt, but server HTML exposes no act ids (verified 2026-09) |

## West Asia (Middle East)

| Jurisdiction | Channel | Status | Evidence / next step |
|---|---|---|---|
| UAE 🇦🇪 | uaelegislation.gov.ae | 🤖 | Browser-challenge page on API paths (verified) |
| Qatar 🇶🇦 | almeezan.qa (Al Meezan) | 🤖 | Connection failed from this network, twice (verified 2026-09) |
| Türkiye 🇹🇷 | mevzuat.gov.tr | 🤖 | TLS certificate chain fails verification (verified) — fetching would require disabling verification, which the charter refuses; robots are empty and `api.mevzuat.gov.tr` is unreachable |
| Israel 🇮🇱 | data.gov.il (CKAN) / knesset | 📄 | data.gov.il robots: `Allow: /`, `Disallow: /api/` (verified) — portal open, its API off-limits; Nevo (full texts) is commercial |
| Saudi Arabia 🇸🇦 | laws.boe.gov.sa | 🔌 | Connection timeout (verified 2026-09); robots.txt itself is empty where reachable |
| Kuwait 🇰🇼 | moj.gov.kw | 📄 | robots.txt 404 (verified); content channel unverified |
| Oman 🇴🇲 | mola.gov.om | 🔌 | DNS does not resolve from the probe network (verified 2026-09) |
| Bahrain 🇧🇭 | legalaffairs.gov.bh | 🤖 | 403 Forbidden on robots.txt itself (verified) |
| Jordan 🇯🇴 | lob.jo | 🔌 | DNS does not resolve from the probe network (verified 2026-09) |
| Lebanon 🇱🇧 | moj.gov.lb | 📄 | No robots.txt (verified); content channel unverified |
| Iran 🇮🇷 | dolat.ir | 🤖 | Challenge/"transferring" interstitial page (verified) |
| Iraq 🇮🇶 | moj.gov.iq | 📄 | robots.txt served as homepage HTML — no rules (verified); content channel unverified |

## Cross-Asia aggregators (interim coverage)

Before a per-country adapter exists, these cover chunks of Asia:

- **[Constitute Project](https://www.constituteproject.org/)** — every
  Asian constitution, downloadable dataset; note the site's robots.txt
  disallows its `.json`/`.xml` endpoints (verified 2026-09), so use the
  published dataset files, not the web endpoints.
- **NATLEX (ILO)** — labour-law texts across Asia, bulk metadata.
- **FAOLEX (FAO)** — food/agriculture/environmental legislation;
  Cloudflare-challenged from this network (2026-09), so plan for its
  bulk download instead of the web API.

## How to extend this map

Probing protocol (keep rows evidence-based): fetch `robots.txt` first,
then one endpoint probe, spaced ≥2 s — record the HTTP code in this
file. Implementing a row: one `SourceAdapter` subclass per jurisdiction
(see `docs/how-to/use-sources.md`); key-gated portals read their
credential from a `LAW_<CC>_*` environment variable, as `LAW_KR_OC`
does, so the adapter ships today and activates on registration.
