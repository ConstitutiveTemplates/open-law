"""Candidate correspondences between different countries' laws.

Whether Japan's 銀行法 *corresponds* to the UK's Banking Act 2009 is a
legal judgment — functional equivalence across legal families rarely
reduces to title similarity. What a machine can do honestly is line up
**candidates**: laws from different jurisdictions that share a primary
topic, have plausibly comparable years, and carry similar titles.
:meth:`find_correspondences` produces those pairs; a human decides.

Similarity is ``difflib`` sequence matching over normalized titles —
deterministic and offline. It is deliberately conservative: it exists
to save review time, not to declare equivalence.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from open_law.coverage import CorpusEntry
from open_law.topics import classify

__all__ = ["Correspondence", "find_correspondences"]

_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)


@dataclass(frozen=True)
class Correspondence:
    """One candidate cross-country correspondence, awaiting human review."""

    topic: str
    jurisdiction_a: str
    title_a: str
    year_a: int | None
    jurisdiction_b: str
    title_b: str
    year_b: int | None
    similarity: float


def _year_of(title: str, promulgation_date: str | None) -> int | None:
    """Best-effort year: the ISO promulgation date wins, else title scan."""
    if promulgation_date and len(promulgation_date) >= 4 and promulgation_date[:4].isdigit():
        return int(promulgation_date[:4])
    year_match = _YEAR_RE.search(title)
    return int(year_match.group(1)) if year_match else None


def _normalized(title: str) -> str:
    """Lowercase title without punctuation, whitespace-collapsed."""
    return re.sub(r"\s+", " ", _NON_WORD_RE.sub(" ", title.lower())).strip()


def _primary_topic(
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


def find_correspondences(
    entries: list[CorpusEntry],
    topics: dict[str, tuple[str, ...]],
    annotations: dict[str, tuple[str, ...]] | None = None,
    *,
    min_similarity: float = 0.5,
    year_window: int = 5,
) -> list[Correspondence]:
    """Candidate pairs across jurisdictions with the same primary topic.

    Laws are grouped by primary topic (annotations first, then the
    keyword classifier's top hit). Within a group, every cross-jurisdiction
    pair whose title similarity clears *min_similarity* — and whose known
    years sit within *year_window* of each other — becomes a candidate,
    best similarity first.
    """
    by_topic: dict[str, list[CorpusEntry]] = defaultdict(list)
    years: dict[str, int | None] = {}
    normalized: dict[str, str] = {}
    for entry in entries:
        primary = _primary_topic(entry, topics, annotations)
        if primary is None:
            continue
        by_topic[primary].append(entry)
        years[entry.key] = _year_of(entry.title, entry.promulgation_date)
        normalized[entry.key] = _normalized(entry.title)

    candidates: list[Correspondence] = []
    for topic, group in by_topic.items():
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                if left.jurisdiction == right.jurisdiction:
                    continue
                year_left, year_right = years[left.key], years[right.key]
                if year_left is not None and year_right is not None and abs(year_left - year_right) > year_window:
                    continue
                similarity = SequenceMatcher(None, normalized[left.key], normalized[right.key]).ratio()
                if similarity >= min_similarity:
                    candidates.append(
                        Correspondence(
                            topic=topic,
                            jurisdiction_a=left.jurisdiction,
                            title_a=left.title,
                            year_a=year_left,
                            jurisdiction_b=right.jurisdiction,
                            title_b=right.title,
                            year_b=year_right,
                            similarity=round(similarity, 3),
                        )
                    )
    candidates.sort(key=lambda candidate: -candidate.similarity)
    return candidates
