# Add your legal expertise to the pipeline

The classification and correspondence features are deliberately
knowledge-starved: the machine matches keywords, and *you* supply the
legal judgment. There are three places to pour expertise in, none of
which require touching Python.

## 1. The taxonomy: what subjects exist, and what words name them

The built-in taxonomy ships 15 topics with Japanese and English
keywords (plus Nepali and Bengali seeds). Export it, edit it, use your
version:

```console
$ uv run open-law taxonomy --export my-taxonomy.json
$ $EDITOR my-taxonomy.json
```

The schema is one JSON object: topic id → keyword list. Keywords are
case-insensitive; Latin ones match on whole words, others (CJK,
Devanagari, Bengali, Lao...) as substrings:

```json
{
  "data-protection": ["個人情報", "プライバシー", "data protection", "privacy"],
  "biosafety": ["バイオセーフティ", "biosafety", "GMO"],
  "digital-markets": ["デジタル市場", "digital markets", "platform regulation"]
}
```

Your file **replaces** the built-in taxonomy completely — you own
exactly what classifies, and every match is traceable to a keyword you
wrote. Use it with any corpus command:

```console
$ uv run open-law coverage corpus.jsonl --taxonomy my-taxonomy.json
$ uv run open-law correspond corpus.jsonl --taxonomy my-taxonomy.json
```

Structural mistakes (empty keyword lists, non-string entries) fail
loudly with the offending topic id.

For a shared, professionally maintained vocabulary, map your topics
onto [EuroVoc](https://op.europa.eu/en/web/eu-vocabularies) concept
labels — the closest existing multilingual legal thesaurus — and note
the mapping in the topic id (e.g. `digital-markets [eurovoc:c_881e]`).

## 2. Annotations: pin your judgment onto specific laws

When the classifier is wrong or silent for a law you know, annotate it.
The file maps `"<source>:<law_id>"` to your topics:

```json
{
  "jp:425AC0000000059": ["banking", "corporate"],
  "uk:ukpga/2018/12": ["data-protection", "telecom"]
}
```

Annotated laws use your topics verbatim; everything else still runs
through the classifier. An annotated topic that is not in the taxonomy
will classify the law for the matrix but read as a custom subject —
add it to the taxonomy too if it should appear as a column.

```console
$ uv run open-law coverage corpus.jsonl --annotations annotations.json
$ uv run open-law correspond corpus.jsonl --annotations annotations.json
```

Over time the annotations file becomes your reviewed ground truth —
exactly the dataset a future LLM-assisted classifier would be trained
and evaluated against.

## 3. Correspondences: candidates for your review

```console
$ uv run open-law correspond corpus.jsonl --min-similarity 0.4
candidates for human review (similarity is title-based, not equivalence):
0.714  [data-protection] GB 2018 'Data Protection Act 2018'  <->  XX 2018 'Data Protection Act 2018'
```

Pairs from different jurisdictions that share a primary topic, sit
within `--year-window` years of each other, and clear
`--min-similarity` title similarity. Silence means *no candidate
pairs*, not *no correspondence*. The output is a review queue, not a
verdict: functional equivalence across legal families is your call,
and this tool's job is to make sure you never start from a blank page.
