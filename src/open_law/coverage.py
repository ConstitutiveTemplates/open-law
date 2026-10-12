"""Country-by-topic coverage matrix from a consolidated corpus.

Comparative questions like "who has no data-protection statute?" are a
matrix computation once laws carry topic tags: rows are jurisdictions,
columns are topics, cells count the laws in the corpus that matched.
:meth:`coverage_matrix` consumes the JSONL lines written by
:command:`open-law dump`, so the workflow is

1. ``open-law dump <source> ... --out corpus.jsonl`` per source,
2. ``open-law coverage corpus.jsonl`` for the matrix and gap report.

**Expert knowledge overrides the classifier.** An annotations file —
``{"<source>:<law_id>": ["topic", ...]}`` — pins human-verified topics
onto specific laws; the keyword classifier only runs where no
annotation exists. Corpus reading, annotation loading, and topic
resolution live in :mod:`open_law.corpus` (shared with
:mod:`open_law.correspond`); this module owns only the matrix and its
gap report.

**What a gap means — and does not mean.** An empty cell says the topic
was *not found in this corpus*, not that the country lacks such a law:
the source may index it under another name, cover only part of the
statute book, or classify it differently. Gaps against a comprehensive
official channel (a national gazette API) are strong signals; gaps
against a partial scrape are a to-check list.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from open_law.corpus import CorpusEntry
from open_law.corpus import iter_corpus
from open_law.corpus import load_annotations
from open_law.corpus import resolve_topics

__all__ = [
    "CorpusEntry",
    "CoverageMatrix",
    "coverage_matrix",
    "gap_report",
    "iter_corpus",
    "load_annotations",
    "topics_for",
]


def topics_for(
    entry: CorpusEntry,
    topics: dict[str, tuple[str, ...]],
    annotations: dict[str, tuple[str, ...]] | None,
) -> tuple[str, ...]:
    """The topics of one corpus entry: annotation first, classifier second.

    Backward-compatible alias of :func:`open_law.corpus.resolve_topics`.
    """
    return resolve_topics(entry, topics, annotations)


@dataclass(frozen=True)
class CoverageMatrix:
    """Laws per (jurisdiction, topic) plus the jurisdictions seen."""

    counts: dict[tuple[str, str], int]
    jurisdictions: tuple[str, ...]

    def has(self, jurisdiction: str, topic: str) -> bool:
        """True when the corpus holds at least one law of this pair."""
        return self.counts.get((jurisdiction, topic), 0) > 0

    def missing_topics(self, jurisdiction: str, topics: Iterable[str]) -> tuple[str, ...]:
        """Topics with no law in this corpus for *jurisdiction*."""
        return tuple(topic for topic in sorted(topics) if not self.has(jurisdiction, topic))


def coverage_matrix(
    jsonl_lines: Iterable[str],
    topics: dict[str, tuple[str, ...]],
    annotations: dict[str, tuple[str, ...]] | None = None,
) -> CoverageMatrix:
    """Build a coverage matrix from JSONL lines of dumped laws.

    Each line is one JSON object as written by ``open-law dump`` (or
    :func:`open_law.dataset.dump_jsonl`) — at minimum ``jurisdiction``
    and ``title``. *topics* is the active taxonomy (see
    :func:`open_law.topics.load_taxonomy`); *annotations* overrides the
    classifier for annotated laws.
    """
    counts: dict[tuple[str, str], int] = {}
    jurisdictions: set[str] = set()
    for entry in iter_corpus(jsonl_lines):
        jurisdictions.add(entry.jurisdiction)
        for topic in resolve_topics(entry, topics, annotations):
            counts[(entry.jurisdiction, topic)] = counts.get((entry.jurisdiction, topic), 0) + 1
    return CoverageMatrix(counts=counts, jurisdictions=tuple(sorted(jurisdictions)))


def gap_report(matrix: CoverageMatrix, topics: Iterable[str]) -> str:
    """Human-readable country-by-topic table plus per-country gaps."""
    topic_list = sorted(topics)
    widths = {topic: max(len(topic), 4) + 2 for topic in topic_list}
    header = f"{'jurisdiction':<14}" + "".join(f"{topic:>{widths[topic]}}" for topic in topic_list)
    lines = [header, "-" * len(header)]
    for jurisdiction in matrix.jurisdictions:
        row = f"{jurisdiction:<14}"
        for topic in topic_list:
            count = matrix.counts.get((jurisdiction, topic), 0)
            row += f"{count or '.':>{widths[topic]}}"
        lines.append(row)
    lines.append("")
    for jurisdiction in matrix.jurisdictions:
        missing = matrix.missing_topics(jurisdiction, topic_list)
        lines.append(f"{jurisdiction}: missing {len(missing)} of {len(topic_list)}: {', '.join(missing)}")
    return "\n".join(lines)
