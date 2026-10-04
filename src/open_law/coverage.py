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
annotation exists.

**What a gap means — and does not mean.** An empty cell says the topic
was *not found in this corpus*, not that the country lacks such a law:
the source may index it under another name, cover only part of the
statute book, or classify it differently. Gaps against a comprehensive
official channel (a national gazette API) are strong signals; gaps
against a partial scrape are a to-check list.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable
from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

from open_law.topics import classify

__all__ = [
    "CoverageMatrix",
    "coverage_matrix",
    "gap_report",
    "iter_corpus",
    "load_annotations",
]


@dataclass(frozen=True)
class CorpusEntry:
    """One parsed law line from a dumped corpus."""

    source: str
    law_id: str
    jurisdiction: str
    title: str
    promulgation_date: str | None

    @property
    def key(self) -> str:
        """The annotations-file key for this law."""
        return f"{self.source}:{self.law_id}"


def iter_corpus(jsonl_lines: Iterable[str]) -> Iterator[CorpusEntry]:
    """Parse dumped JSONL lines, tolerating corrupt or foreign lines."""
    for raw_line in jsonl_lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            decoded = cast("object", json.loads(line))
        except json.JSONDecodeError:
            continue
        if not isinstance(decoded, dict):
            continue
        entry = cast("dict[str, object]", decoded)
        jurisdiction = entry.get("jurisdiction")
        title = entry.get("title")
        if not isinstance(jurisdiction, str) or not isinstance(title, str):
            continue
        source = entry.get("source")
        law_id = entry.get("law_id")
        promulgation_date = entry.get("promulgation_date")
        yield CorpusEntry(
            source=source if isinstance(source, str) else "",
            law_id=law_id if isinstance(law_id, str) else "",
            jurisdiction=jurisdiction,
            title=title,
            promulgation_date=promulgation_date if isinstance(promulgation_date, str) else None,
        )


def load_annotations(path: str) -> dict[str, tuple[str, ...]]:
    """Load an expert annotations file (``{"<source>:<id>": [topics]}``).

    Raises ``ValueError`` on structural problems so a typo'd file fails
    loudly instead of silently un-classifying laws.
    """
    try:
        with pathlib.Path(path).open(encoding="utf-8") as annotations_file:
            decoded = cast("object", json.load(annotations_file))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"annotations file {path!r} is unreadable: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(decoded, dict):
        msg = f"annotations file {path!r} must be a JSON object"
        raise TypeError(msg)
    annotations: dict[str, tuple[str, ...]] = {}
    for key, topics in cast("dict[str, object]", decoded).items():
        if not isinstance(topics, list) or not topics:
            msg = f"annotations entry {key!r} must map to a non-empty topic list"
            raise ValueError(msg)
        topics_list = cast("list[object]", topics)
        if any(not isinstance(topic, str) for topic in topics_list):
            msg = f"annotations entry {key!r} has a non-string topic"
            raise ValueError(msg)
        annotations[key] = tuple(cast("list[str]", topics_list))
    return annotations


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


def topics_for(
    entry: CorpusEntry,
    topics: dict[str, tuple[str, ...]],
    annotations: dict[str, tuple[str, ...]] | None,
) -> tuple[str, ...]:
    """The topics of one corpus entry: annotation first, classifier second."""
    if annotations and entry.key in annotations:
        return annotations[entry.key]
    return classify(topics, entry.title)


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
        for topic in topics_for(entry, topics, annotations):
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
