# open-law

Scrape and consolidate legislation from around the world — politely.

open-law wraps each jurisdiction's **official** publication channel
(an API or a bulk data endpoint) in a `SourceAdapter` and normalizes the
results into one JSON shape. Every fetch goes through a shared polite
fetcher: robots.txt first, per-host rate limits and budgets, on-disk
cache, and a contactable User-Agent — the Good-future charter.

Built-in sources (`open-law sources` prints the live registry):

| id | jurisdiction | channel |
|----|--------------|---------|
| `bd` | Bangladesh | bdlaws (Ministry of Law, Justice and Parliamentary Affairs) |
| `ca` | Canada | Justice Laws Website (Department of Justice), consolidated XML |
| `de` | Germany | Gesetze im Internet (BMJ/BfJ) |
| `eu` | European Union | EUR-Lex / Publications Office CELLAR, by CELEX |
| `jlt` | Japan | Japanese Law Translation (Ministry of Justice), official English TMX |
| `jp` | Japan | e-Gov 法令検索 (Digital Agency) |
| `kr` | South Korea | 국가법령정보센터 DRF (Ministry of Government Legislation), key-gated |
| `la` | Laos | Lao Official Gazette, PDF full texts |
| `mv` | Maldives | mvlaw (Attorney General's Office) |
| `np` | Nepal | Nepal Law Commission |
| `uk` | United Kingdom | legislation.gov.uk, XML + native Akoma Ntoso |
| `us` | United States | eCFR — Code of Federal Regulations |
| `us-tx` | Texas (US) | Texas Constitution and Statutes (Texas Legislature) |

For the rest of Asia, the
[coverage map](explanations/asia-coverage.md) records each
jurisdiction's channel status and next step.
See the [how-to guide](how-to/use-sources.md) for usage and for adding a
jurisdiction, and the [OSS landscape evaluation](explanations/oss-evaluation.md)
for why each building block was adopted or rejected.

## Installation

open-law is not on PyPI yet and has no release tag, so install it from
GitHub with [uv](https://docs.astral.sh/uv/), pinned to a commit (an
example below — use `@<tag>` once releases exist):

```console
$ uv tool install git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a
```

See [Installation](tutorials/installation.md) for one-off runs, the
`pdf` extra, and library use.

## Usage

The fetcher refuses live requests until `FETCHER_CONTACT` holds an
address site operators can reach:

```console
$ export FETCHER_CONTACT=you@example.org
$ open-law sources
$ open-law search jp 銀行法 --limit 3
$ open-law fetch uk ukcm/2023/1
```

## Language

English is the canonical language of these docs; Japanese versions, where
they exist, are translations kept to the same standard.

## Not legal advice

politeuma records what legal sources say and which engineering practices
they support. It does not decide whether your product complies with any
law, and using it does not make anything compliant. Sources can go out of
date or be misread, so every rule shows its sources and the date it was
last checked. Contributors and reviewers share their understanding in good
faith; their contributions are not legal advice to you or anyone else.
