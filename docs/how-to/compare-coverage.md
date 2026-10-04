# Compare legal coverage across countries

The comparative question this answers: **"which country does not cover
topic X (in our corpus)?"** — a country-by-topic coverage matrix built
from laws you have dumped with `open-law dump`.

## The workflow

```console
# 1. Build the corpus: fetch laws from every source you care about
$ uv run open-law dump uk ukpga/2009/1 ukpga/2018/12 --out corpus.jsonl
$ uv run open-law dump bd --ids-from bd-act-ids.txt --out corpus.jsonl.bd
$ cat corpus.jsonl.bd >> corpus.jsonl

# 2. The matrix: rows = jurisdictions, columns = topics
$ uv run open-law coverage corpus.jsonl

# 3. Machine-readable version
$ uv run open-law coverage corpus.jsonl --json
```

The table counts laws per (jurisdiction, topic); the report below it
lists, per country, the topics the corpus does **not** cover.

## How laws get their topics

`open_law.topics.classify` matches a hand-authored, multilingual
keyword taxonomy (`TOPICS` in `src/open_law/topics.py`) against the
title — title hits count triple — and, when available, the full text.
Japanese keywords match as substrings, Latin ones on word boundaries.
Every hit is a keyword you can point at, so disagreements are fixed by
editing `TOPICS`, not by tuning anything.

The planned second stage is LLM-assisted classification over the same
fixed taxonomy (same output shape, better recall on titles that
describe the subject indirectly). The taxonomy, not the model, is the
interface.

## What a gap means — and what it does not

An empty cell says the topic was **not found in this corpus**. It does
not say the country lacks such a law:

- the source may index it under a different name, or classify it as
  subsidiary legislation;
- the source may cover only part of the statute book (the adapter for
  Bangladesh fetches by id — if you dumped three acts, three acts is
  all the matrix can speak about);
- the topic may sit inside a broader law whose title does not name it
  (a banking act's data-protection provisions are invisible to a
  title-only classifier).

Gaps against a comprehensive official channel (a national gazette API)
are strong signals; gaps against a partial fetch are a to-check list.
Treat this as triage for comparative research, never as a finding.

## Correspondence between countries' laws

The matrix answers presence/absence. Whether Japan's 銀行法
*corresponds* to the UK's Banking Act 2009 is a legal judgment —
functional equivalence across legal families (civil, common, religious)
rarely reduces to title similarity. The pipeline's role is to line up
**candidate correspondences** (same topic, similar scope, comparable
dates) for human review; that clustering step is not implemented yet.

For established cross-border infrastructure, lean on:

- **EuroVoc** — the EU's multilingual thesaurus for classifying
  legislation; the closest existing common vocabulary.
- **ELI (European Legislation Identifier)** — cross-border identifiers
  for EU member states' laws.
- **Comparative Constitutions Project** — constitutional provisions
  mapped by topic across (almost) all countries.
- **UNCTAD trackers** — country-by-topic presence for cyber, data
  protection, and AI legislation.

## Important precedents

Case-law comparison needs a different pipeline: CourtListener (via
Free Law Project's juriscraper — the same project evaluated in
[the OSS landscape review](oss-evaluation.md)) ranks US/CA/UK cases by
citation networks. "Leading cases" lists for civil-law jurisdictions
are curated by scholars, not scrapeable generically; the practical path
is curated seed lists per jurisdiction, then citation-graph expansion.
