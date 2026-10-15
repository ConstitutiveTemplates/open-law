# Good-future Charter — open-law

This project follows the **Good-future-python** charter: code that stays
usable, lawful, and kind to the network it touches. Every rule below is
enforced by the toolchain (ruff / pytest / CI), not left to discipline —
if you break one, the checks fail first.

## 1. Respect the source

- **Feed first, API second, scraping last.** Before scraping an HTML page,
  `preflight(url)` judges the site: after robots.txt, working feed endpoints (`/feed`,
  `/rss.xml`, `/atom.xml`, ...) are probed in order, then machine-API
  hints (`/api`, `api.` subdomain, `openapi.json`). When a feed exists,
  fetch the feed — not the page. When an API is found, use it instead of
  scraping. `fetch_text()` applies the feed switch automatically.
- **robots.txt is law.** Every fetch goes through `src/open_law/fetcher.py`,
  whose single send path runs in a fixed order — robots.txt, wait, send,
  count — so robots.txt is read before any other request to a host
  (including the `api.` subdomain and every discovery probe). Never bypass
  it with a raw `requests.get` / `httpx.get` / `urlopen` — ruff's
  `banned-api` rejects those calls outside the fetcher.
- **Denied means denied.** A `401`/`403` raises `AccessDeniedError` — do
  not retry around the block, rotate user-agents, or reach for a CAPTCHA
  solver. The site said no: use its API or ask permission.
- **Rate-limit yourself, and stay inside the budget.** At most one request
  per second per host (`delay_seconds`, enforced by sleep — not by
  promise — on every request, probes included), and at most `max_requests_per_host` (default 100) requests per
  host per session — *including* the preflight probes (HEAD, robots.txt,
  feed/API discovery), which are cached per origin so repeat pages cost
  one probe instead of a dozen. Exceeding the budget raises
  `BudgetExceededError`:
  what is polite at 10 requests is a DDoS at 10 000 — stop and ask before
  scaling up. Scrapy's `AUTOTHROTTLE` / `DOWNLOAD_DELAY` and memorious'
  `http_rate_limit` carry the same rule for their engines. The knobs are
  reachable from the CLI (`--budget`, `--delay`, `--contact`), and a
  `dump` that hits the budget writes what it fetched and tells you how to
  resume instead of throwing the batch away.
- **Cache aggressively.** GET responses live in the platform user cache
  (`FetchConfig.cache_dir`, default `<user cache>/open-law/fetch`) for a
  day, keyed by the URL *and* the request's content-negotiation headers,
  so an EUR-Lex RDF fetch is never served an HTML body. Text and binary
  bodies are cached separately: a PDF is stored as bytes and never
  round-tripped through UTF-8. Re-runs and tests must never refetch what
  is already cached, and a cache hit does not wait for a rate-limit slot.
- **Identify yourself.** The `User-Agent` always carries this project's name
  plus a contact address (`FETCHER_CONTACT`) so the operator can reach you.
  While it is still the `contact@example.com` placeholder, the fetcher
  refuses every live request with `ContactRequiredError`.

## 2. Respect the law

- **Copyright stays attached.** The project license is
  **Apache-2.0** (see `LICENSE`). Dependency licenses are
  audited by `just license-check` (`pip-licenses --fail-on`): copyleft the
  project license cannot absorb fails the build.
- **No CAPTCHA-solving.** This project never generates CAPTCHA-bypass
  helpers (2captcha-style solvers, token injectors). If a site blocks bots,
  use its API or ask permission — bypassing bot protection violates the
  site's terms and likely the law (cf. CFAA / 不正アクセス禁止法).
- **Personal data stays personal.** Scraped data containing personal
  information is handled conservatively: suppress identifiers, keep salts
  out of the repo, log transfers.

## 3. Respect the commons

- **FAIR when it matters.** Every source adapter declares the licence its
  data is reused under (`open-law sources` prints it); datasets built from
  open-law keep that attribution, and carry DUO use-conditions and CARE
  governance notes where they apply.
- **Leave no trace in git.** Caches (`.cache/`), downloaded pages, browser
  profiles, and credentials are git-ignored. Commit code and configs —
  never harvested data.
- **Ask before scaling up.** A polite single-host crawl is the default. Mass
  crawls, distributed queues, and proxy rotation need explicit review (open
  an issue first) — what is polite at 1 req/s is a DDoS at 1000 req/s.

## 4. The charter is tested, not promised

§1 is not prose about good intentions: each promise has a test that fails
when the code stops honouring it. They live in `tests/test_charter.py`;
run them with `just test` or `uv run pytest tests/test_charter.py`.

| Promise | Test |
|---|---|
| robots.txt is read before any other request to a host | `test_no_request_precedes_the_robots_check` |
| a robots.txt refusal stops the crawl | `test_robots_denial_stops_the_crawl` |
| at most one request per second per host, probes included | `test_requests_per_host_never_exceed_one_per_second` |
| robots.txt, HEAD and discovery probes count against the budget | `test_robots_head_and_discovery_count_toward_the_budget` |
| the defaults carry the charter's numbers; a cached body skips the wait | `test_defaults_are_the_charter_defaults` |
| the placeholder contact refuses the request outright | `test_placeholder_contact_refuses_the_request` |

`tests/test_scraping.py` covers the same ground per mechanism (feed-first
discovery, access denial, one send path, binary caching); the tests above
are the charter's own copy, written to be read next to the rules.
