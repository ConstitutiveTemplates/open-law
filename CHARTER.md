# Good-future Charter — open-law

This project follows the **Good-future-python** charter: code that stays
usable, lawful, and kind to the network it touches. Every rule below is
enforced by the toolchain (ruff / pytest / CI), not left to discipline —
if you break one, the checks fail first.

## 1. Respect the source

- **Feed first, API second, scraping last.** Before scraping an HTML page,
  `preflight(url)` judges the site: working feed endpoints (`/feed`,
  `/rss.xml`, `/atom.xml`, ...) are probed in order, then machine-API
  hints (`/api`, `api.` subdomain, `openapi.json`). When a feed exists,
  fetch the feed — not the page. When an API is found, use it instead of
  scraping. `fetch_text()` applies the feed switch automatically.
- **robots.txt is law.** Every fetch goes through `src/open_law/fetcher.py`
  (or the engine starter: `spider.py` / `crawler.py` / `browser_fetch.py`),
  which checks robots.txt before the first byte. Never bypass it with a raw
  `requests.get` / `httpx.get` / `urlopen` — ruff's `banned-api` rejects
  those calls outside the fetcher.
- **Denied means denied.** A `401`/`403` raises `AccessDeniedError` — do
  not retry around the block, rotate user-agents, or reach for a CAPTCHA
  solver. The site said no: use its API or ask permission.
- **Rate-limit yourself, and stay inside the budget.** At most one request
  per second per host (`delay_seconds`, enforced by sleep — not by
  promise), and at most `max_requests_per_host` (default 100) requests per
  host per session — *including* the preflight probes (HEAD, robots.txt,
  feed/API discovery), which are cached per origin so repeat pages cost
  one probe instead of a dozen. Exceeding the budget raises
  `BudgetExceededError`:
  what is polite at 10 requests is a DDoS at 10 000 — stop and ask before
  scaling up. Scrapy's `AUTOTHROTTLE` / `DOWNLOAD_DELAY` and memorious'
  `http_rate_limit` carry the same rule for their engines.
- **Cache aggressively.** GET responses live under `.cache/fetcher/` for a
  day; re-runs and tests must never refetch what is already cached.
- **Identify yourself.** The `User-Agent` always carries this project's name
  plus a contact address (`FETCHER_CONTACT`). Replace the placeholder before
  any real crawl so the operator can reach you.

## 2. Respect the law

- **Copyright stays attached.** The project license is
  **MIT** (see `LICENSE`). Dependency licenses are
  audited by `task license-check` (`pip-licenses --fail-on`): copyleft the
  project license cannot absorb fails the build.
- **No CAPTCHA-solving.** This template never generates CAPTCHA-bypass
  helpers (2captcha-style solvers, token injectors). If a site blocks bots,
  use its API or ask permission — bypassing bot protection violates the
  site's terms and likely the law (cf. CFAA / 不正アクセス禁止法).
- **Personal data stays personal.** Scraped data containing personal
  information is handled under the same bar as `data/DEIDENTIFICATION.md`:
  suppress identifiers, keep salts out of the repo, log transfers.

## 3. Respect the commons

- **FAIR when it matters.** Research software ships citation metadata
  (`CITATION.cff`) and SPDX annotations (`REUSE.toml`); datasets carry DUO
  use-conditions and CARE governance notes where they apply.
- **Leave no trace in git.** Caches (`.cache/`), downloaded pages, browser
  profiles, and credentials are git-ignored. Commit code and configs —
  never harvested data.
- **Ask before scaling up.** A polite single-host crawl is the default. Mass
  crawls, distributed queues, and proxy rotation need explicit review (open
  an issue first) — what is polite at 1 req/s is a DDoS at 1000 req/s.
