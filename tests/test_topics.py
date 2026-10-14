"""Topic classification tests."""

from __future__ import annotations

import pytest

from pathlib import Path


from open_law.topics import DEFAULT_TOPICS, classify, classify_evidence, load_taxonomy


def test_classifies_japanese_title_by_substring() -> None:
    assert "banking" in classify(DEFAULT_TOPICS, "銀行法")
    assert "data-protection" in classify(DEFAULT_TOPICS, "個人情報の保護に関する法律")


def test_classifies_english_title_by_word_boundaries() -> None:
    topics = classify(DEFAULT_TOPICS, "Data Protection Act 2018")
    assert "data-protection" in topics


def test_classifies_new_adapter_landmark_titles() -> None:
    """CA/US landmark titles added with those adapters classify correctly."""
    assert "data-protection" in classify(DEFAULT_TOPICS, "Personal Information Protection and Electronic Documents Act")
    assert "data-protection" in classify(DEFAULT_TOPICS, "PART 312 — CHILDREN'S ONLINE PRIVACY PROTECTION RULE")
    assert "criminal" in classify(DEFAULT_TOPICS, "Criminal Code")


def test_latin_keywords_respect_word_boundaries() -> None:
    """Word boundaries: 'tax' must not fire inside unrelated 'taxidermy'."""
    assert classify(DEFAULT_TOPICS, "Taxidermy Licensing Act") == ()


def test_short_cjk_keyword_does_not_fire_inside_a_longer_keyword() -> None:
    """電気 (energy) nested in 電気通信 (telecom) is a false positive."""
    topics = classify(DEFAULT_TOPICS, "電気通信事業法")
    assert "telecom" in topics
    assert "energy" not in topics
    # …while 電気 heading its own compound still counts as energy.
    assert classify(DEFAULT_TOPICS, "電気事業法") == ("energy",)


def test_devanagari_keyword_must_end_a_word() -> None:
    """कर (tax) matches आयकर (income tax), not the कर inside करना ("to do")."""
    assert classify(DEFAULT_TOPICS, "करना प्रक्रिया") == ()
    assert "tax" in classify(DEFAULT_TOPICS, "आयकर अधिनियम")


def test_single_character_keyword_is_matched_in_the_title_only() -> None:
    """One character says nothing in a statute body, everything in a title."""
    assert "tax" in classify(DEFAULT_TOPICS, "税法")
    assert classify(DEFAULT_TOPICS, "Debt Recovery Act", "本文のどこかに税の話が出てくる") == ()


def test_algorithm_alone_is_not_an_ai_cue() -> None:
    """Bare 'algorithm' flagged every statute that mentions algorithms as AI law."""
    assert "algorithm" not in DEFAULT_TOPICS["ai"]
    assert classify(DEFAULT_TOPICS, "Algorithm Regulation Act") == ()


def test_classify_evidence_names_the_matched_terms() -> None:
    """Every classification carries the keywords that produced it."""
    banking = next(match for match in classify_evidence(DEFAULT_TOPICS, "銀行法") if match.topic == "banking")
    assert "銀行" in banking.terms
    assert banking.score == 3  # one title hit, counting triple

    on_text = classify_evidence(DEFAULT_TOPICS, "Debt Recovery Act", "a worker paid taxation this year")
    text_topics = {match.topic: match.terms for match in on_text}
    assert "taxation" in text_topics["tax"]
    assert "worker" in text_topics["labor"]


def test_title_hits_outweigh_text_hits() -> None:
    title_topics = classify(DEFAULT_TOPICS, "環境基本法", "これは税と会社に関する本文です")
    assert title_topics[0] == "environment"


def test_unmatched_title_is_empty() -> None:
    assert classify(DEFAULT_TOPICS, "Nepal Law Commission Act") == ()


def test_new_expert_languages_are_in_the_default_taxonomy() -> None:
    """Nepali and Bengali keywords ship alongside Japanese and English."""
    assert "बैंक" in DEFAULT_TOPICS["banking"]
    assert "শ্রম" in DEFAULT_TOPICS["labor"]
    assert "ऐन" not in DEFAULT_TOPICS["banking"]  # generic 'act' is not a banking cue


def test_taxonomy_loader_rejects_structural_problems(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"broken": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty keyword list"):
        load_taxonomy(str(bad))

    unreadable = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="unreadable"):
        load_taxonomy(str(unreadable))


def test_taxonomy_loader_accepts_expert_replacement(tmp_path: Path) -> None:
    expert = tmp_path / "taxonomy.json"
    expert.write_text(
        '{"biosafety": ["バイオセーフティ", "biosafety"], "tax": ["taxation"]}',
        encoding="utf-8",
    )
    taxonomy = load_taxonomy(str(expert))
    assert set(taxonomy) == {"biosafety", "tax"}  # replacement, not merge
    assert classify(taxonomy, "Biosafety Framework Act") == ("biosafety",)
