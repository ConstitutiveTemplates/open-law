# Fetch budgets and politeness

Every request in open-law goes through `open_law.fetcher.PoliteFetcher`.
One config controls politeness per adapter: delay, budget, timeout, and cache.

## Defaults

```python
from open_law.fetcher import FetchConfig

FetchConfig(
    delay_seconds=1.0,          # per-host rate limit
    timeout_seconds=10.0,        # httpx timeout
    cache_ttl_seconds=86400,     # 1 day on-disk cache
    max_requests_per_host=100,   # session budget
)
```

The CLI builds the fetcher from the adapter's `crawl_delay_seconds` via
`open_law.sources.default_fetcher` — no manual wiring needed for normal use.
For custom runs, construct `PoliteFetcher(FetchConfig(...))` directly and pass
it to `open_adapter(source_id, fetcher=...)`.

## Per-adapter tuning

Each adapter declares the crawl delay its site asks for (robots.txt `Crawl-delay`).
Build the recommended fetcher with that delay; other knobs stay at defaults
unless the site is known-slow or known-large.

| source | adapter class | `crawl_delay_seconds` | `max_requests_per_host` | `timeout_seconds` | `cache_ttl_seconds` |
|--------|---------------|----------------------:|------------------------:|-----------------:|--------------------:|
| `np`   | NepalLawCommissionAdapter | 10.0 | 100 | 10 | 86400 |
| `la`   | LaoGazetteAdapter | 2.0 | 100 | 10 | 86400 |
| `uk`   | LegislationGovUkAdapter | 5.0 | 100 | 10 | 86400 |
| `bd`   | BangladeshLawsAdapter | 2.0 | 100 | 10 | 86400 |
| `ca`   | JusticeLawsAdapter | 2.0 | 100 | 10 | 86400 |
| `de`   | GesetzeImInternetAdapter | 2.0 | 100 | 10 | 86400 |
| `us-tx`| TexasStatutesAdapter | 2.0 | 100 | 10 | 86400 |
| `mv`   | MvLawAdapter | 2.0 | 100 | 10 | 86400 |
| `eu`   | EurlexAdapter | 1.0 | 100 | 10 | 86400 |
| `jp`   | EgovAdapter | 1.0 | 100 | 10 | 86400 |
| `kr`   | KoreaLawAdapter | 1.0 | 100 | 10 | 86400 |
| `us-ecfr` | EcfrAdapter | 1.0 | 100 | 10 | 86400 |
| `jlt`  | JltAdapter | 2.0 | 100 | 10 | 86400 |

> `np` mirrors the server's `Crawl-delay: 10`; `la` has no robots.txt, so 2 s
> is conservative. `uk` mirrors `Crawl-delay: 5`. Others stay at the 1 s
> (or 2 s) defaults declared in `src/open_law/sources/*.py`.

Example — a 10 s fetcher for Nepal, a 1 s fetcher for eCFR:

```python
from open_law.fetcher import FetchConfig, PoliteFetcher
from open_law.sources.np import NepalLawCommissionAdapter
from open_law.sources.us_ecfr import EcfrAdapter
from open_law.sources import open_adapter

np_adapter = open_adapter("np", fetcher=PoliteFetcher(FetchConfig(delay_seconds=NepalLawCommissionAdapter.crawl_delay_seconds)))
us_adapter = open_adapter("us-ecfr")  # default_fetcher already uses EcfrAdapter.crawl_delay_seconds
```

## Bulk-dump math

The budget counts **requests**, not laws, and the overhead lands before the
first law is written. A cold origin costs up to 14 requests — robots.txt
(1), the preflight HEAD probe (1), up to 8 feed probes and 3 API probes,
plus robots.txt for the `api.` host — so a first `dump` writes about **86
laws** out of a 100-request budget. A later run (bodies cached, fresh
process) costs robots.txt plus one GET per law: **99 laws**. Adapter
fetches skip discovery entirely (`discover=False`), so within one process
each further page is one request.

Wall time for a bulk `dump` is `requests × delay_seconds`:

- `np` at 10 s × 100 requests = 1 000 s ≈ **16 min 40 s per 100 requests (~86–99 ids)**
- `uk` at 5 s × 100 requests = 500 s ≈ 8 min 20 s
- `bd`/`ca`/`de`/`us-tx`/`la` at 2 s × 100 = 200 s ≈ 3 min 20 s
- defaults at 1 s × 100 = 100 s ≈ 1 min 40 s

Raise the budget for a large harvest — the politeness rules are per host
per session, so a bigger budget is a deliberate decision, not a bug:

```console
$ uv run open-law dump uk --ids-from uk-ids.txt --out laws.jsonl --budget 1000 --delay 5
$ uv run open-law fetch uk ukcm/2023/1 --contact you@example.org
```

When the budget runs out mid-batch, the dump keeps what it fetched, reports
`host budget reached after N of M law(s)`, writes the ids it never reached
to `laws.jsonl.remaining`, and prints the command that resumes the run:

```console
$ uv run open-law fetch uk ukcm/2023/1 --out laws.jsonl  # stopped at the budget
open-law: host budget reached after 86 of 120 law(s); 34 id(s) not fetched
open-law: resume with: open-law dump uk --ids-from laws.jsonl.remaining --out laws.jsonl --budget 200
```

Resuming is cheap: everything already written is in the cache, so the
second run only pays for the ids it still needs.

The on-disk cache lives in the platform user cache
(`FetchConfig.cache_dir`, `<user cache>/open-law/fetch` by default, TTL 1
day) and is keyed by the URL *and* the request's content-negotiation
headers, so CELLAR's RDF and HTML bodies never collide. Re-runs are free.
When a site returns 5xx or is transiently unreachable, `FetchConfig(wayback_fallback=True)`
and `open-law fetch --wayback` fall back to `https://archive.org/wayback/available?url=`
(4xx never falls back — the charter forbids bypassing access control); the
snapshot is fetched through its raw `id_` URL, so a PDF comes back as the
archived file rather than a re-encoded page. See
[`use-sources.md`](use-sources.md#fetch-budgets) for the CLI side.
