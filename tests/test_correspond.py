"""Correspondence candidate tests."""

from __future__ import annotations

from open_law.correspond import _language_of
from open_law.correspond import find_correspondences
from open_law.corpus import CorpusEntry
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


def test_cross_language_pair_is_proposed_by_topic_and_era() -> None:
    """銀行法 ↔ Banking Act 2009: a candidate by topic and era, never scored.

    The memo's own example: title similarity across Japanese and English is
    ~0 and means nothing, so the pair is offered unscored for review.
    """
    entries = [
        _entry("jp", "1", "JP", "銀行法"),
        _entry("uk", "2", "GB", "Banking Act 2009", "2009-02-12"),
    ]
    candidates = find_correspondences(entries, DEFAULT_TOPICS)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.topic == "banking"
    assert candidate.similarity is None
    assert candidate.basis == "topic+era"
    assert "銀行" in candidate.terms_a
    assert "banking act" in candidate.terms_b


def test_jlt_english_title_bridges_a_japanese_law() -> None:
    """The corpus's jlt entry scores a JP law in English against a UK one."""
    entries = [
        _entry("jp", "1", "JP", "銀行法", "1981-06-01"),
        _entry("jlt", "4913", "JP", "Banking Act", "1981-06-01"),
        _entry("uk", "2", "GB", "Banking Act 2009", "2009-02-12"),
    ]
    # The memo's example spans a generation, so the era window is raised
    # here; the point of the test is the bridge, not the window.
    candidates = find_correspondences(entries, DEFAULT_TOPICS, year_window=30)
    bridged = [candidate for candidate in candidates if candidate.basis == "bridge"]
    assert bridged, [(candidate.basis, candidate.title_a, candidate.title_b) for candidate in candidates]
    assert bridged[0].similarity is not None
    assert bridged[0].similarity >= 0.5
    assert (bridged[0].title_a, bridged[0].title_b) == ("銀行法", "Banking Act 2009")


def test_same_language_titles_below_the_floor_are_dropped() -> None:
    """Within one language the similarity floor still applies."""
    entries = [
        _entry("uk", "1", "GB", "Data Protection Act 2018"),
        _entry("xx", "2", "XX", "Privacy Regulation of Records"),
    ]
    # Both are data-protection laws in Latin script, but the titles are not
    # similar, so no candidate is proposed.
    assert find_correspondences(entries, DEFAULT_TOPICS) == []


def test_scriptless_title_pairs_on_topic_and_era_only() -> None:
    """A title in no recognised script has no language to compare with."""
    entries = [
        _entry("xx", "1", "XX", "①②③"),
        _entry("yy", "2", "YY", "Data Protection Act 2018"),
    ]
    annotations = {"xx:1": ("data-protection",), "yy:2": ("data-protection",)}
    assert _language_of("①②③") == "unknown"
    candidates = find_correspondences(entries, DEFAULT_TOPICS, annotations)
    assert len(candidates) == 1
    assert candidates[0].similarity is None
    assert candidates[0].basis == "topic+era"


def test_language_buckets_are_script_based() -> None:
    """Titles are only compared with titles in the same script."""
    assert _language_of("Data Protection Act 2018") == "latin"
    assert _language_of("銀行法") == "cjk"
    assert _language_of("은행법") == "hangul"
