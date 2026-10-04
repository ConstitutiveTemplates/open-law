# open-law

Scrape and consolidate legislation from around the world — politely.

open-law wraps each jurisdiction's **official** publication channel
(an API or a bulk data endpoint) in a `SourceAdapter` and normalizes the
results into one JSON shape. Every fetch goes through a shared polite
fetcher: robots.txt first, per-host rate limits and budgets, on-disk
cache, and a contactable User-Agent — the Good-future charter.

Built-in sources: `uk` (legislation.gov.uk, XML + native Akoma Ntoso),
`jp` (e-Gov 法令 v2), `kr` (국가법령정보센터 DRF), `bd` (bdlaws), `np`
(Nepal Law Commission), `la` (Lao Official Gazette), `eu` (EU
Publications Office CELLAR by CELEX). For the rest of Asia, the
[coverage map](explanations/asia-coverage.md) records each
jurisdiction's channel status and next step.
See the [how-to guide](how-to/use-sources.md) for usage and for adding a
jurisdiction, and the [OSS landscape evaluation](explanations/oss-evaluation.md)
for why each building block was adopted or rejected.

## Installation

```console
$ pip install open-law
```

## Usage

```console
$ open-law sources
$ open-law search jp 銀行法 --limit 3
$ open-law fetch uk ukcm/2023/1
```
