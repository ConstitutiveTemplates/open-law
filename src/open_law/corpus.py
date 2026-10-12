"""Shared corpus plumbing for the analysis commands.

:mod:`open_law.coverage` (country-by-topic matrix) and
:mod:`open_law.correspond` (cross-country candidates) both start from
the same place: the JSONL lines written by ``open-law dump``, plus the
optional expert annotations file pinning human-verified topics onto
specific laws. This module owns that shared ground — the parsed
:class:`CorpusEntry`, the tolerant :func:`iter_corpus` reader, the
:func:`load_annotations` loader, and the "annotation first, classifier
second" topic resolution — so neither analysis duplicates it.
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
    "CorpusEntry",
    "iter_corpus",
    "load_annotations",
    "resolve_primary_topic",
    "resolve_topics",
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


def resolve_topics(
    entry: CorpusEntry,
    topics: dict[str, tuple[str, ...]],
    annotations: dict[str, tuple[str, ...]] | None,
) -> tuple[str, ...]:
    """All topics of one corpus entry: annotation first, classifier second."""
    if annotations and entry.key in annotations:
        return annotations[entry.key]
    return classify(topics, entry.title)


def resolve_primary_topic(
    entry: CorpusEntry,
    topics: dict[str, tuple[str, ...]],
    annotations: dict[str, tuple[str, ...]] | None,
) -> str | None:
    """The expert annotation's first topic, else the classifier's top hit."""
    if annotations is not None:
        annotated = annotations.get(entry.key)
        if annotated:
            return annotated[0]
    return next(iter(classify(topics, entry.title)), None)
