"""Correspondence candidate tests."""

from __future__ import annotations

from open_law.correspond import find_correspondences
from open_law.coverage import CorpusEntry
from open_law.topics import DEFAULT_TOPICS


def _entry(source: str, law_id: str, jurisdiction: str, title: str, date: str | None = None) -> CorpusEntry:
    return CorpusEntry(source=source, law_id=law_id, jurisdiction=jurisdiction, title=title, promulgation_date=date)


def test_similar_titles_across_jurisdictions_become_candidates() -> None:
    entries = [
        _entry("uk", "1", "GB", "Data Protection Act 2018", "2018-05-25"),
        _entry("mt", "2", "MT", "Data Protection Act 2018", "2018-12-04"),
    ]
    candidates = find_correspondences(entries, DEFAULT_TOPICS)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.topic == "data-protection"
    assert candidate.similarity == 1.0
    assert (candidate.jurisdiction_a, candidate.jurisdiction_b) == ("GB", "MT")


def test_year_gap_outside_window_blocks_the_pair() -> None:
    entries = [
        _entry("uk", "1", "GB", "Data Protection Act 2018", "2018-05-25"),
        _entry("xx", "2", "XX", "Data Protection Act 2050", "2050-01-01"),
    ]
    assert find_correspondences(entries, DEFAULT_TOPICS, year_window=5) == []
    assert len(find_correspondences(entries, DEFAULT_TOPICS, year_window=100)) == 1


def test_dissimilar_titles_are_not_candidates() -> None:
    entries = [
        _entry("uk", "1", "GB", "Data Protection Act 2018"),
        _entry("jp", "2", "JP", "高原開発推進法"),
    ]
    assert find_correspondences(entries, DEFAULT_TOPICS) == []


def test_same_jurisdiction_pairs_never_match() -> None:
    entries = [
        _entry("uk", "1", "GB", "Data Protection Act 2018"),
        _entry("uk", "2", "GB", "Data Protection Act 2018"),
    ]
    assert find_correspondences(entries, DEFAULT_TOPICS) == []


def test_annotations_override_the_classifier() -> None:
    entries = [
        _entry("uk", "1", "GB", "Some Unnamed Act 2020"),
        _entry("xx", "2", "XX", "Another Unnamed Act 2021"),
    ]
    annotations = {
        "uk:1": ("biosafety",),
        "xx:2": ("biosafety",),
    }
    expert_topics = {"biosafety": ("biosafety framework",)}
    candidates = find_correspondences(entries, expert_topics, annotations, min_similarity=0.3)
    assert candidates and candidates[0].topic == "biosafety"
