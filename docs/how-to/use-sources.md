# Fetch laws from the built-in sources

open-law ships one adapter per jurisdiction, each wrapping that
country's *official* publication channel — an API or a bulk data
endpoint, never a scraped HTML page when a machine channel exists.

The examples run from a clone with `uv run`; after
`uv tool install` (see [Installation](../tutorials/installation.md)),
drop the `uv run` prefix. Live commands need a reachable contact
address first — the fetcher refuses to send requests under the
`contact@example.com` placeholder:

```console
$ export FETCHER_CONTACT=you@example.org
```

## The source registry

```console
$ uv run open-law sources
```

prints one line per source: id, jurisdiction, provider, homepage, and
the license under which its data is reused. The ids on the left are
what every other command calls `SOURCE`.

## Search and fetch

```console
# Title-search Japan's law list (no registration needed)
$ uv run open-law search jp 銀行法 --limit 3

# Fetch one law's metadata as JSON
$ uv run open-law fetch uk ukcm/2023/1
$ uv run open-law fetch eu 32022R2065
```

`fetch` prints the unified JSON: identity (`source`, `jurisdiction`,
`channel`, `law_id`), title and dates, the machine-readable `text_url`,
an `akn_url` when the source offers Akoma Ntoso, and source-specific
`extras` (a JSON object). `search` prints the same shape minus
full-text locations. Version dates are `last_amended` (the most recent
amendment the source reports, `None` when it states none — never a
fetch date) and `consolidated_as_of` (the point-in-time the served
text reflects).

`fetch jp <law_id>` mixes two e-Gov API versions by design: title
search runs against the v2 `/laws` endpoint, but the body text still
comes from the v1 `lawdata` full-text XML — v1 returns the current
consolidation with no revision history of its own, so amendment
awareness comes from the v2 `revision_info` shape alone
(`amendment_promulgate_date` → `last_amended`,
`amendment_enforcement_date` → `consolidated_as_of`). No registration
is needed (the elsur application key is only required for the newer
v2 document endpoints, which open-law does not use). Korea still needs
its key: `search kr` activates once
the ``LAW_KR_OC`` open-API id (issued at openapi.law.go.kr, bound to
your server IP — without it the API answers "required-input
verification failed") is set in the environment.

```console
# US federal regulations (eCFR — no key, structured XML)
$ uv run open-law search us-ecfr "children online privacy" --limit 5
$ uv run open-law fetch us-ecfr title-16/part-312        # the COPPA Rule
$ uv run open-law fetch us-ecfr title-16/part-312/section-312.5
```

The `us-ecfr` source wraps the eCFR public API: `search` is full-text across
all 50 titles and maps each hit to an eCFR path (`title-N[/part-P|
/section-S]`), `fetch` returns that node's dated XML. The id says
`us-ecfr` (not `us`) because the channel is regulations only: statutes
(the US Code) sit on a different channel (uscode.house.gov) that is
currently bot-gated and out of scope — regulations are the
machine-readable bulk of US regulatory law.

```console
# Canada's consolidated federal statutes (Justice Laws Website XML)
$ uv run open-law fetch ca P-8.6    # PIPEDA — Personal Information Protection and Electronic Documents Act
$ uv run open-law fetch ca C-46     # Criminal Code (~6 MB consolidation)
```

The `ca` source has no machine keyword search (the legacy search form
returns an empty page to machines) — fetch by act code from the
human acts index. The XML carries the consolidation's point-in-time
date as `consolidated_as_of`, the `lastAmendedDate` as `last_amended`,
and the in-force flag in `extras`.

```console
# Japan's official English translations (JLT — Ministry of Justice)
$ uv run open-law fetch jlt 4913     # Labor Standards Act, TMX bilingual
$ uv run open-law fetch jlt 4848     # Civil Code Parts I-III
```

The `jlt` source serves the Ministry of Justice's official English
translations: `fetch` resolves the law's view page and returns the TMX
1.4 download (`text_url`) — a translation memory of ja/en provision
pairs — with PDF/TXT alternates in `extras`. Keyword search is
CSRF-gated to machines, so `search` declines; the per-law ids come from
the human index. This is the *English* side of the same statute book
`jp` (e-Gov) indexes in Japanese.

```console
# Germany's federal statutes (Gesetze im Internet — no key, static index + HTML)
$ uv run open-law search de BGB --limit 3
$ uv run open-law fetch de bgb        # Bürgerliches Gesetzbuch — text_url is the full-HTML Gesamtausgabe
```

The `de` source wraps the BMJ/BfJ portal: `search` matches the query
against the alphabetical `Teilliste_<LETTER>.html` index (abbreviation
and title), `fetch` takes the portal folder (`bgb`, `stgb`) and points
`text_url` at the full-HTML edition for `text` to strip. Per-law
`xml.zip` packages exist on the same pages for bulk consumers.

```console
# Texas statutes (TCAS JSON search + static chapter HTML — no key)
$ uv run open-law search us-tx biometric --limit 5
$ uv run open-law fetch us-tx BC.503   # Business & Commerce Code ch. 503 (CUBI — biometric identifiers)
```

The `us-tx` source wraps the Texas Legislature's TCAS backend: `search`
is full-text across all codes via the key-free `TCASSearch` JSON API
(results map to `<CODE>.<chapter>` ids), `fetch` serves the chapter's
static HTML from the state file server. A trailing section
(`BC.503.001`) narrows to the same chapter file — sections share one
document. California (`leginfo.legislature.ca.gov`) is Cloudflare-gated
(403 to machines) and Illinois (`ilga.gov`) is unreachable from
datacenter networks — both are documented in
`docs/explanations/jurisdiction-coverage.md`, not shipped as adapters.

```console
# Maldives legislation (mvlaw — no key, server-rendered index + consolidation pages)
$ uv run open-law search mv "27/2025" --limit 5
$ uv run open-law fetch mv 291        # Zakaath Act 27/2025 — text_url is the latest consolidation
```

The `mv` source wraps the Attorney General's Office mvlaw database:
`search` walks the server-rendered `/dv/legislations?page=<n>` index
(20 rows per page, matching title and legislation number), `fetch`
takes the numeric legislation id and follows the show route to the
latest consolidation page, whose embedded section tree is the full
text. The `/api/v1/` JSON router the site bundles advertise answers
401 without a session, so the adapter reads the server-rendered pages
instead. Content language is Dhivehi (`div`).

## Read the full text

```console
$ uv run open-law text bd 43        # HTML page -> plain text
$ uv run open-law text uk ukpga/1989/6 | head -40
```

`text` refetches the law's `text_url` through the polite fetcher (the
on-disk cache makes it free right after a `fetch`) and strips it to
plain text: XML sources extract character data, HTML pages strip tags.
Sources whose full text is a PDF (Laos) are extracted with `pypdf` when
the `pdf` extra is installed; without it, `text` refuses and points at
the file. Scanned PDFs without a text layer come back empty.

Search results and fetched laws carry ISO-8601 `promulgation_date`
values; the source's original spelling is preserved in `extras`
(`promulgation_date_raw`, `document_date`, ...).

## Consolidate a batch as JSONL

```console
$ uv run open-law dump bd 43 1004 --out laws.jsonl
$ cat laws.jsonl | jq .title
```

`dump` fetches every id through one adapter and writes one JSON object
per line (`--out` writes a file; without it, JSONL goes to stdout).
For bulk runs, pass ids from a file or stdin, one per line — handy when
the id list comes from an index or a script:

```console
$ uv run open-law dump bd --ids-from bd-act-ids.txt --out laws.jsonl
$ grep -oE 'act-details-[0-9]+' index.html | cut -d- -f3 | uv run open-law dump bd --ids-from - -o laws.jsonl
```

Fetches happen before the file is created, so a failing id never leaves
a partial file behind. JSONL is the interchange format for the
consolidation pipeline: jq, DuckDB (`read_jsonl`), and pandas all read
it directly.

## Judge a URL before crawling it

```console
$ uv run open-law preflight https://example.com/feed
```

prints the fetcher's judgement as JSON: feed/API discovery, robots.txt
verdict, and per-host budget state — the check the charter asks for
before crawling a new site. It is not free: it reads robots.txt first,
then sends a HEAD to the URL and probes the feed and API endpoints, all
rate-limited and counted toward the host budget.

## Politeness is per source

Each adapter class declares its own `crawl_delay_seconds` (mirroring
the source's robots.txt `Crawl-delay`, such as legislation.gov.uk's 5)
and `http_headers` (CELLAR's content negotiation). The CLI builds the
default fetcher from those declarations, so every request is polite by
construction; responses are cached under `.cache/fetcher/` for a day.

## Fetch budgets

Recommended `FetchConfig` per adapter (delay × budget × timeout × cache):

| source | `crawl_delay_seconds` | `max_requests_per_host` | `timeout_seconds` | `cache_ttl_seconds` | notes |
|--------|----------------------:|------------------------:|-----------------:|--------------------:|-------|
| `np`   | 10.0                | 100                   | 10             | 86400 (1 day)     | `Crawl-delay: 10` on lawcommission.gov.np |
| `la`   | 2.0                 | 100                   | 10             | 86400             | no robots.txt — conservative 2 s |
| `uk`   | 5.0                 | 100                   | 10             | 86400             | `Crawl-delay: 5` on legislation.gov.uk |
| `bd`   | 2.0                 | 100                   | 10             | 86400             | UTF-16 pages, no robots.txt |
| `ca`   | 2.0                 | 100                   | 10             | 86400             | ~5.8 MB for `C-46`, still budget-safe |
| `de`   | 2.0                 | 100                   | 10             | 86400             | ~486 KB indexes, ~3 MB for `bgb` |
| `us-tx`| 2.0                 | 100                   | 10             | 86400             | |
| `mv`   | 2.0                 | 100                   | 10             | 86400             | server-rendered pages (~200–865 KB) |
| others | 1.0                 | 100                   | 10             | 86400             | `eu`, `jp`, `kr`, `us-ecfr`, `jlt` — defaults |

Build a tuned fetcher with `FetchConfig(delay_seconds=Adapter.crawl_delay_seconds)` via
`open_law.sources.default_fetcher`, or construct `PoliteFetcher(FetchConfig(...))` directly.
See `docs/how-to/fetch-budgets.md` for the full matrix, retry guidance with `--wayback`,
and bulk-dump timing.

## Live probes

Live network probes are opt-in. Run one cheap fetch per registered adapter with:

```console
$ OPEN_LAW_LIVE=1 uv run pytest -m live -q
```

Without `OPEN_LAW_LIVE=1` the `live` tests are skipped (they are also excluded by default
via `-m "not live"`). `kr` additionally requires `LAW_KR_OC` (the open-API id at
openapi.law.go.kr, bound to the caller's IP).

## Add a new jurisdiction

1. Subclass `open_law.sources.adapter.SourceAdapter` in
   `src/open_law/sources/<country>.py`; implement `search` and `fetch`,
   parsing into `open_law.models.LawSummary` / `Law`. If a capability
   is genuinely unavailable, raise `NotAvailableBySourceError` with the
   actionable next step.
2. Fetch through `self._get(url)` — never raw httpx (ruff bans it).
3. Register the class in `src/open_law/sources/__init__.py`.
4. Capture one real response as `tests/fixtures/*.xml|json` and test
   the adapter offline against it (see `tests/test_sources_uk.py`).

Before writing an adapter, check
[the OSS evaluation](../explanations/oss-evaluation.md) — the source
may already have an API, a bulk download, or a known-dead channel.
