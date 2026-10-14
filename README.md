# open-law

Polite fetchers for official legislation APIs: 13 sources (UK, Japan, EU,
US eCFR and more) in one JSON shape.

<div align="center">

[![CI](https://github.com/politeuma/open-law/actions/workflows/ci.yml/badge.svg)](https://github.com/politeuma/open-law/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/politeuma/open-law/branch/main/graph/badge.svg)](https://codecov.io/gh/politeuma/open-law)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776AB.svg?logo=python&logoColor=white)](https://github.com/politeuma/open-law)
[![Documentation](https://img.shields.io/badge/docs-politeuma.github.io%2Fopen--law-8A2BE2?logo=gitbook&logoColor=white)](https://politeuma.github.io/open-law)

</div>

- **Who it's for:** developers, researchers and legal-tech projects that
  need legislation from official channels in machine-readable form, and
  want to fetch it without hammering government servers.
- **What it does:** wraps each jurisdiction's official API or bulk
  endpoint in one adapter, returns every law in the same JSON shape
  (with Akoma Ntoso locations when the source offers them), and enforces
  robots.txt, per-host rate limits, a disk cache and a contactable
  User-Agent in one shared fetcher.
- **What it isn't:** a scraper that gets around bot protection, a
  complete legal database, or legal advice.

## 30-second demo

```sh
export FETCHER_CONTACT=you@example.org   # your address goes into the User-Agent
open-law() { uvx --from git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a open-law "$@"; }

open-law sources                         # list the 13 jurisdiction adapters
open-law search jp 銀行法 --limit 3       # title-search e-Gov's law list
open-law fetch uk ukpga/1989/6           # one law's metadata as JSON
open-law fetch eu 32022R2065             # EU law by CELEX number
open-law dump bd 43 1004 --out laws.jsonl  # consolidate several laws as JSONL
```

The fetcher refuses to contact any site until `FETCHER_CONTACT` holds an
address the site's operators can reach.

## Install

open-law is not on PyPI yet, and no release has been tagged, so install it
from GitHub with [uv](https://docs.astral.sh/uv/) and pin a commit (switch
to `@<tag>` once releases exist). The commit below is an example — pick the
latest from the [commit history](https://github.com/politeuma/open-law/commits/main).

```sh
# Put `open-law` on your PATH
uv tool install git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a

# PDF full texts (Laos) need the pdf extra
uv tool install 'open-law[pdf] @ git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a'
```

Or as a library (`uv add 'open-law @ git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a'`):

```python
from open_law.sources import open_adapter

law = open_adapter("uk").fetch("ukpga/1989/6")
print(law.title, law.akn_url)
```

### Sources

`uk` (legislation.gov.uk XML + native Akoma Ntoso), `jp` (e-Gov 法令),
`jlt` (Japanese Law Translation, official English TMX), `kr`
(국가법령정보센터 DRF, key-gated), `eu` (Publications Office CELLAR by
CELEX), `us` (eCFR — US federal regulations), `us-tx` (Texas Constitution
and Statutes), `ca` (Justice Laws Website), `de` (Gesetze im Internet),
`bd` (bdlaws), `np` (Nepal Law Commission), `la` (Lao Official Gazette,
PDF full texts) and `mv` (mvlaw — Maldives AGO). Adding a jurisdiction is
one `SourceAdapter` subclass plus one registry line; the
[Asia coverage map](docs/explanations/asia-coverage.md) records every
Asian jurisdiction's channel status.

Beyond fetching, `open-law coverage` turns a corpus into a
country-by-topic matrix, and `open-law correspond` lines up candidate
cross-country correspondences that experts refine through editable
taxonomy and annotation files.

### Polite by construction

Every request goes through `fetcher.py` under the
[Good-future charter](CHARTER.md): robots.txt first, 1 request per second
per host (or the site's `Crawl-delay`), request budgets, an on-disk
cache, and a contactable User-Agent. Direct HTTP calls (`requests.get`,
`httpx.get`, `urlopen`) are banned by ruff outside the fetcher, and
CAPTCHA-solving helpers are out of scope — if a site blocks bots, use its
API or ask permission.

See the [documentation](https://politeuma.github.io/open-law) for
tutorials, how-to guides and the API reference.

## Where it fits in politeuma

[politeuma](https://github.com/politeuma) turns legal requirements into
short, sourced rules that sit next to your code. open-law is its source
layer: it reads the statutes and regulations those rules cite from their
official publishers, so the citations in
[law-map](https://github.com/politeuma/law-map) can be checked against the
current text. It is an optional, standalone tool — nothing else in
politeuma needs it installed, and it is useful on its own for anyone who
needs legislation as data.

While open-law is 0.x, its CLI, JSON shape and Python API may change
without notice.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](.github/CONTRIBUTING.md)
for development setup, checks and template updates,
[AGENTS.md](AGENTS.md) for AI-agent guidance, and
[SECURITY.md](SECURITY.md) to report a vulnerability.

English is the canonical language of this project's docs; Japanese
versions, where they exist, are translations kept to the same standard.

## License

[Apache-2.0](LICENSE)

**Not legal advice.** Engineering guardrails with citations; ask a
qualified professional for compliance decisions.

<!-- README only content. Anything below this line won't be included in index.md -->

See https://politeuma.github.io/open-law for more detailed documentation.
