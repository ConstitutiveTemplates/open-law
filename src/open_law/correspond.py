"""Candidate correspondences between different countries' laws.

Whether Japan's 銀行法 *corresponds* to the UK's Banking Act 2009 is a
legal judgment — functional equivalence across legal families rarely
reduces to title similarity. What a machine can do honestly is line up
**candidates**, and say *why* each pair was proposed:

- ``title`` — both titles are in the same language (same script) and
  their similarity clears ``min_similarity``;
- ``bridge`` — the titles are in different languages, but the
  non-English law has an official English rendering in the corpus (the
  ``jlt`` adapter's translations of Japanese statutes) that is similar to
  the other side's title;
- ``topic+era`` — same primary topic and comparable years, with no
  language bridge to score. The pair is offered for review, not rated.

Similarity is never computed *across* languages: ``difflib`` over
``銀行法`` and ``Banking Act 2009`` returns ~0 and means nothing. Every
candidate also carries the keywords that classified each side, so a
proposal can be traced back to the taxonomy. A human decides;
:func:`find_correspondences` only saves review time.

Corpus plumbing (:class:`CorpusEntry`, annotation loading, primary-topic
resolution) lives in :mod:`open_law.corpus`, shared with
:mod:`open_law.coverage`; this module owns only candidate pairing.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from open_law.corpus import CorpusEntry
from open_law.corpus import resolve_primary_topic
from open_law.topics import classify_evidence

__all__ = ["Correspondence", "find_correspondences"]

_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)

# The jlt adapter renders Japanese statutes in official English; those
# titles are the only cross-language bridge in the corpus.
_BRIDGE_SOURCE = "jlt"

# Script buckets, used to decide whether two titles are comparable
# strings at all. Deliberately coarse: any Latin-script title is compared
# with any other Latin-script title, and a CJK title is compared with
# nothing except through a bridge.
_SCRIPT_BUCKETS: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("latin", ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F), (0x1E00, 0x1EFF))),
    ("cjk", ((0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))),
    ("hangul", ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7A3))),
    ("devanagari", ((0x0900, 0x097F),)),
    ("bengali", ((0x0980, 0x09FF),)),
    ("thaana", ((0x0780, 0x07BF),)),
    ("lao", ((0x0E80, 0x0EFF),)),
    ("cyrillic", ((0x0400, 0x04FF),)),
    ("arabic", ((0x0600, 0x06FF),)),
)


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
    # None when the pair was proposed on topic and era alone (no language
    # bridge to score the titles with).
    similarity: float | None
    # "title" | "bridge" | "topic+era" — why this pair was proposed.
    basis: str
    # Keywords that classified each side, so the proposal is traceable.
    terms_a: tuple[str, ...]
    terms_b: tuple[str, ...]


def _year_of(title: str, promulgation_date: str | None) -> int | None:
    """Best-effort year: the ISO promulgation date wins, else title scan."""
    if promulgation_date and len(promulgation_date) >= 4 and promulgation_date[:4].isdigit():
        return int(promulgation_date[:4])
    year_match = _YEAR_RE.search(title)
    return int(year_match.group(1)) if year_match else None


def _normalized(title: str) -> str:
    """Lowercase title without punctuation, whitespace-collapsed."""
    return re.sub(r"\s+", " ", _NON_WORD_RE.sub(" ", title.lower())).strip()


def _language_of(title: str) -> str:
    """Coarse language bucket for *title*, by dominant script.

    Not a language detector: two Latin-script titles share a bucket, which
    is the point — they are comparable strings. A CJK title and a Latin
    one are not, however similar the laws are.
    """
    counts: dict[str, int] = {}
    for char in title:
        code = ord(char)
        for name, ranges in _SCRIPT_BUCKETS:
            if any(start <= code <= end for start, end in ranges):
                counts[name] = counts.get(name, 0) + 1
                break
    if not counts:
        return "unknown"
    return max(sorted(counts), key=lambda name: counts[name])


def _within_era(left: int | None, right: int | None, year_window: int) -> bool:
    """True when the years are comparable (unknown years never block)."""
    if left is None or right is None:
        return True
    return abs(left - right) <= year_window


def _bridge_titles(
    entry: CorpusEntry,
    bridges: list[CorpusEntry],
    years: dict[str, int | None],
    normalized: dict[str, str],
    year_window: int,
) -> tuple[str, ...]:
    """Normalized English titles of *entry*'s law, from bridge entries."""
    return tuple(
        normalized[bridge.key] for bridge in bridges if _within_era(years[entry.key], years[bridge.key], year_window)
    )


@dataclass(frozen=True)
class _Corpus:
    """The per-law facts candidate pairing needs, keyed by corpus key."""

    by_topic: dict[str, list[CorpusEntry]]
    years: dict[str, int | None]
    normalized: dict[str, str]
    languages: dict[str, str]
    terms: dict[str, tuple[str, ...]]
    bridges: dict[str, tuple[str, ...]]


def _collect(
    entries: list[CorpusEntry],
    topics: dict[str, tuple[str, ...]],
    annotations: dict[str, tuple[str, ...]] | None,
    year_window: int,
) -> _Corpus:
    """Group *entries* by primary topic and gather what pairing needs."""
    by_topic: dict[str, list[CorpusEntry]] = defaultdict(list)
    years: dict[str, int | None] = {}
    normalized: dict[str, str] = {}
    languages: dict[str, str] = {}
    terms: dict[str, tuple[str, ...]] = {}
    for entry in entries:
        primary = resolve_primary_topic(entry, topics, annotations)
        if primary is None:
            continue
        by_topic[primary].append(entry)
        years[entry.key] = _year_of(entry.title, entry.promulgation_date)
        normalized[entry.key] = _normalized(entry.title)
        languages[entry.key] = _language_of(entry.title)
        terms[entry.key] = _terms_for(entry, primary, topics, annotations)

    bridges: dict[str, tuple[str, ...]] = {}
    for group in by_topic.values():
        bridge_entries = [entry for entry in group if entry.source == _BRIDGE_SOURCE]
        if not bridge_entries:
            continue
        for entry in group:
            if entry.source == _BRIDGE_SOURCE or languages[entry.key] == "latin":
                continue
            bridges[entry.key] = _bridge_titles(entry, bridge_entries, years, normalized, year_window)
    return _Corpus(
        by_topic=by_topic,
        years=years,
        normalized=normalized,
        languages=languages,
        terms=terms,
        bridges=bridges,
    )


def _candidates_for_topic(
    topic: str,
    group: list[CorpusEntry],
    corpus: _Corpus,
    *,
    min_similarity: float,
    year_window: int,
) -> list[Correspondence]:
    """Every candidate pair inside one topic's group."""
    found: list[Correspondence] = []
    for index, left in enumerate(group):
        for right in group[index + 1 :]:
            if left.jurisdiction == right.jurisdiction:
                continue
            if not _within_era(corpus.years[left.key], corpus.years[right.key], year_window):
                continue
            scored = _score_pair(left, right, corpus, min_similarity)
            if scored is None:
                continue
            similarity, basis = scored
            found.append(
                Correspondence(
                    topic=topic,
                    jurisdiction_a=left.jurisdiction,
                    title_a=left.title,
                    year_a=corpus.years[left.key],
                    jurisdiction_b=right.jurisdiction,
                    title_b=right.title,
                    year_b=corpus.years[right.key],
                    similarity=similarity,
                    basis=basis,
                    terms_a=corpus.terms[left.key],
                    terms_b=corpus.terms[right.key],
                )
            )
    return found


def _terms_for(
    entry: CorpusEntry,
    primary: str,
    topics: dict[str, tuple[str, ...]],
    annotations: dict[str, tuple[str, ...]] | None,
) -> tuple[str, ...]:
    """Keywords behind *entry*'s primary topic (empty for expert annotations)."""
    if annotations and entry.key in annotations:
        return ()
    return next(
        (match.terms for match in classify_evidence(topics, entry.title) if match.topic == primary),
        (),
    )


def _score_pair(
    left: CorpusEntry,
    right: CorpusEntry,
    corpus: _Corpus,
    min_similarity: float,
) -> tuple[float | None, str] | None:
    """(similarity, basis) for *left*/*right*, or None when it is no candidate."""
    languages = corpus.languages
    if languages[left.key] == languages[right.key] != "unknown":
        similarity = SequenceMatcher(None, corpus.normalized[left.key], corpus.normalized[right.key]).ratio()
        if similarity < min_similarity:
            return None
        return round(similarity, 3), "title"
    # Different languages: a bridge makes the English titles comparable.
    latin = next((entry for entry in (left, right) if languages[entry.key] == "latin"), None)
    if latin is not None:
        other = right if latin is left else left
        bridge_titles = corpus.bridges.get(other.key, ())
        if bridge_titles:
            best = max(SequenceMatcher(None, corpus.normalized[latin.key], title).ratio() for title in bridge_titles)
            if best >= min_similarity:
                return round(best, 3), "bridge"
            # The bridge is guessed from topic and era, not verified: a low
            # score may mean "wrong translation", not "different law", so
            # the pair stays a topic+era candidate rather than disappearing.
    return None, "topic+era"


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
    pair whose known years sit within *year_window* becomes a candidate:
    scored by title similarity when both titles are in the same language,
    by the corpus's English bridge titles when they are not, and offered
    unscored when neither applies. Scored candidates come first.
    """
    corpus = _collect(entries, topics, annotations, year_window)
    candidates: list[Correspondence] = []
    for topic, group in corpus.by_topic.items():
        candidates.extend(
            _candidates_for_topic(topic, group, corpus, min_similarity=min_similarity, year_window=year_window)
        )
    candidates.sort(
        key=lambda candidate: (
            candidate.similarity is None,
            -(candidate.similarity or 0.0),
            candidate.topic,
            candidate.jurisdiction_a,
            candidate.title_a,
            candidate.jurisdiction_b,
            candidate.title_b,
        )
    )
    return candidates
