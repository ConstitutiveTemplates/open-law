# Fetch laws from the built-in sources

open-law ships one adapter per jurisdiction, each wrapping that
country's *official* publication channel — an API or a bulk data
endpoint, never a scraped HTML page when a machine channel exists.

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
`law_id`), title and dates, the machine-readable `text_url`, an
`akn_url` when the source offers Akoma Ntoso, and source-specific
`extras`. `search` prints the same shape minus full-text locations.
`fetch jp <law_id>` deliberately fails with the registration URL —
e-Gov's full-text endpoint requires a (free) application key; the
metadata list does not. The same pattern applies to Korea: `search kr`
activates once the ``LAW_KR_OC`` open-API id (issued at
openapi.law.go.kr) is set in the environment.

```console
# US federal regulations (eCFR — no key, structured XML)
$ uv run open-law search us "children online privacy" --limit 5
$ uv run open-law fetch us title-16/part-312        # the COPPA Rule
$ uv run open-law fetch us title-16/part-312/section-312.5
```

The `us` source wraps the eCFR public API: `search` is full-text across
all 50 titles and maps each hit to an eCFR path (`title-N[/part-P|
/section-S]`), `fetch` returns that node's dated XML. Statutes (the US
Code) sit on a different channel (uscode.house.gov) that is currently
bot-gated and out of scope — regulations are the machine-readable bulk
of US regulatory law.

## Read the full text

```console
$ uv run open-law text bd 43        # HTML page -> plain text
$ uv run open-law text uk ukpga/1989/6 | head -40
```

`text` refetches the law's `text_url` through the polite fetcher (the
on-disk cache makes it free right after a `fetch`) and strips it to
plain text: XML sources extract character data, HTML pages strip tags.
Sources whose full text is a PDF (Laos) refuse and point at the file.

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
verdict, and per-host budget state — the tool the charter runs before
any page fetch.

## Politeness is per source

Each adapter class declares its own `crawl_delay_seconds` (mirroring
the source's robots.txt `Crawl-delay`, such as legislation.gov.uk's 5)
and `http_headers` (CELLAR's content negotiation). The CLI builds the
default fetcher from those declarations, so every request is polite by
construction; responses are cached under `.cache/fetcher/` for a day.

## Add a new jurisdiction

1. Subclass `open_law.sources.base.SourceAdapter` in
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
