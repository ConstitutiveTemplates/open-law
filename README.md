# open_law

*Scrape and consolidate legislation from around the world*

**open_law** fetches legislation from official publication channels —
one polite adapter per jurisdiction, unified into a single JSON shape
with Akoma Ntoso locations surfaced whenever a source offers them.

<div align="center">

[![CI](https://github.com/politeuma/open-law/actions/workflows/ci.yml/badge.svg)](https://github.com/politeuma/open-law/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/politeuma/open-law/branch/main/graph/badge.svg)](https://codecov.io/gh/politeuma/open-law)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776AB.svg?logo=python&logoColor=white)](https://github.com/politeuma/open-law)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-black.json)](https://github.com/copier-org/copier)
[![Documentation](https://img.shields.io/badge/docs-politeuma.github.io%2Fopen--law-8A2BE2?logo=gitbook&logoColor=white)](https://politeuma.github.io/open-law)

</div>

---

## ✨ Features

- **Source adapters** — `uk` (legislation.gov.uk XML + native Akoma
  Ntoso), `jp` (e-Gov 法令 v2 JSON law list), `kr` (국가법령정보센터 DRF,
  key-gated), `bd` (bdlaws, English-text laws of Bangladesh), `np`
  (Nepal Law Commission, Crawl-delay 10), `la` (Lao Official Gazette,
  PDF full texts), `eu` (Publications Office CELLAR by CELEX),
  `us` (eCFR — US federal regulations, key-free JSON + XML),
  `jlt` (MoJ official English translations, TMX), `mv` (mvlaw —
  Maldives AGO legislation database); adding
  a jurisdiction is one
  subclass plus one registry line — see the
  [Asia coverage map](docs/explanations/asia-coverage.md) for every
  Asian jurisdiction's channel status
- **Consolidation & comparison** — `open-law dump` batches any number
  of law ids into one JSONL file (or stdout); `open-law coverage` turns
  a corpus into a country-by-topic matrix and reports, per country,
  which topics the corpus does not cover; `open-law correspond` lines
  up candidate cross-country correspondences, and experts inject their
  judgment via editable taxonomy and annotations files (no Python)
- **Polite by construction** — robots.txt gating, per-host `Crawl-delay`
  mirroring, request budgets, on-disk cache, and a contactable
  User-Agent, all enforced in `fetcher.py` under the
  [Good-future charter](CHARTER.md)
- **API-first, scraping last** — adapters fetch known machine endpoints;
  direct HTTP calls are banned project-wide by ruff, and CAPTCHA-solving
  helpers are out of scope forever

## 📦 Installation

open-law is not on PyPI yet, and no release has been tagged, so install it
from GitHub with [uv](https://docs.astral.sh/uv/) and pin a commit (switch
to `@<tag>` once releases exist). The commit below is an example — pick the
latest from the [commit history](https://github.com/politeuma/open-law/commits/main).

```sh
# Run once without installing anything
uvx --from git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a open-law sources

# Or put `open-law` on your PATH
uv tool install git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a

# PDF full texts (Laos) need the pdf extra
uv tool install 'open-law[pdf] @ git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a'
```



## 🚀 Quick start

The fetcher refuses to contact any site until you give it an address the
site's operators can reach (it goes into the User-Agent):

```sh
export FETCHER_CONTACT=you@example.org     # replace with your own address
open-law sources                           # list the jurisdiction adapters
open-law search jp 銀行法 --limit 3         # title-search e-Gov's law list
open-law fetch uk ukcm/2023/1              # one law's metadata as JSON
open-law fetch eu 32022R2065               # EU law by CELEX number
open-law dump bd 43 1004 --out laws.jsonl  # consolidate as JSONL
open-law preflight https://example.com/feed
```

From a clone (see Development setup below), prefix the
commands with `uv run`.

Or as a library (`uv add 'open-law @ git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a'`):

```python
from open_law.sources import open_adapter

law = open_adapter("uk").fetch("ukpga/1989/6")
print(law.title, law.akn_url)
```


The project also ships a **polite web-fetching layer** under the
[Good-future charter](CHARTER.md) (robots.txt first, 1 req/s per host,
on-disk cache, contactable User-Agent):

```sh
FETCHER_CONTACT=you@example.org uv run python -c "from open_law.fetcher import fetch_text; print(fetch_text('https://example.com/')[:200])"
# tests run fully offline: pytest tests/test_scraping.py -q
```

Direct HTTP calls (`requests.get`, `httpx.get`, `urlopen`) are banned by
ruff outside the fetcher, so every fetch stays polite. CAPTCHA-solving
helpers are never generated — if a site blocks bots, use its API or ask
permission.



> [!TIP]
> See the [documentation](https://politeuma.github.io/open-law) for tutorials, how-to guides and the API reference.


## 🧰 What's included

What            | Where
:---:           | :---:
Source          | <https://github.com/politeuma/open-law>
Documentation   | <https://politeuma.github.io/open-law>
Releases        | <https://github.com/politeuma/open-law/releases>
Security        | [SECURITY.md](SECURITY.md) — how to report a vulnerability
Agent guide     | [AGENTS.md](AGENTS.md) — instructions for AI coding agents


## 🛠️ Development setup


Prerequisites: Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/politeuma/open-law.git
cd open-law
uv sync                      # create .venv and install everything (incl. dev deps)

```

Before committing, run the `fix` task to auto-fix formatting and lint
(`ruff check --fix` + `ruff format`); repo hygiene (secret scanning, workflow
linting, conventional commit messages) is enforced in CI.


### Environment variables

Copy the example file and adjust the values:

```sh
cp .env.example .env
```

`.env` is loaded automatically by [direnv](https://direnv.net) (see `.envrc`)
and by the Docker stack; it is git-ignored, so never commit real secrets.




### Lint, type-check and test

The project uses [Just](https://just.systems) to drive the common commands:

```sh
just lint
just test
just check

```


See [AGENTS.md](AGENTS.md) for AI-agent guidance (commands, edit scope, commit rules).

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for details on contributing,
running tests and making a release.


## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](.github/CONTRIBUTING.md) and the
[issue tracker](https://github.com/politeuma/open-law/issues).

## 🔄 Updating from the template

This project records its template answers in `.copier-answers.yml`, so it can
receive template improvements later. To update:

```sh
uvx copier update --trust --defaults
```

Resolve any conflicts, run `just fix` and
`just check`, then commit. See the template's
[adopt/update guide](https://politeuma.github.io/architekton-py/main/how-to/update-template/)
for the conflict-resolution workflow.


## 📄 License

[Apache-2.0](LICENSE)

<!-- README only content. Anything below this line won't be included in index.md -->

See https://politeuma.github.io/open-law for more detailed documentation.
