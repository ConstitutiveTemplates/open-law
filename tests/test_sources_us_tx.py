"""Texas statutes adapter tests, offline against captured TCAS responses."""

from __future__ import annotations

import pytest

from tests.helpers import FixtureLoader, Offline, RecordingSite

from open_law.sources.us_tx import TexasStatutesAdapter


def test_search_finds_biometric_chapter(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        TexasStatutesAdapter,
        recording_site({"/api/TCASSearch/GetPage/1/ZZ/biometric": fixture_text("ustx_search_biometric.json")}, seen),
    )
    results = adapter.search("biometric")
    assert len(results) >= 2
    cubi = next(r for r in results if r.law_id == "BC.503")
    assert cubi.source == "us-tx"
    assert cubi.jurisdiction == "US-TX"
    assert cubi.title == "BUSINESS AND COMMERCE CODE CHAPTER 503. BIOMETRIC IDENTIFIERS"
    assert cubi.url == "https://statutes.capitol.texas.gov/Docs/BC/htm/BC.503.htm"
    assert ("document_code", "BC") in cubi.extras
    assert "https://tcss.legis.texas.gov/api/TCASSearch/GetPage/1/ZZ/biometric" in seen


def test_search_respects_limit(offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader) -> None:
    adapter = offline(
        TexasStatutesAdapter,
        recording_site({"/api/TCASSearch/GetPage/1/ZZ/biometric": fixture_text("ustx_search_biometric.json")}, []),
    )
    assert len(adapter.search("biometric", limit=1)) == 1


def test_search_malformed_json_raises(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(
        TexasStatutesAdapter,
        recording_site({"/api/TCASSearch/GetPage/1/ZZ/biometric": "definitely { not json"}, []),
    )
    with pytest.raises(ValueError, match="malformed JSON"):
        adapter.search("biometric")


def test_search_without_results_returns_empty(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(
        TexasStatutesAdapter,
        recording_site({"/api/TCASSearch/GetPage/1/ZZ/biometric": "[]"}, []),
    )
    assert adapter.search("biometric") == []


def test_fetch_returns_chapter_with_file_text_url(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        TexasStatutesAdapter,
        recording_site({"/resources/BC/htm/BC.503.htm": fixture_text("ustx_BC.503.htm")}, seen),
    )
    law = adapter.fetch("BC.503.001")
    assert law.source == "us-tx"
    assert law.law_id == "BC.503"
    assert law.title == "BUSINESS AND COMMERCE CODE  CHAPTER 503.  BIOMETRIC IDENTIFIERS"
    assert law.language == "eng"
    assert law.text_url == "https://tcss.legis.texas.gov/resources/BC/htm/BC.503.htm"
    assert ("format", "tcas-html") in law.extras
    assert ("chapter", "503") in law.extras
    assert seen == [
        "https://tcss.legis.texas.gov/robots.txt",
        "https://tcss.legis.texas.gov/resources/BC/htm/BC.503.htm",
    ]


def test_fetch_rejects_unknown_id(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(TexasStatutesAdapter, recording_site({}, []))
    with pytest.raises(ValueError, match="Unrecognised Texas statute id"):
        adapter.fetch("not-a-statute!!!")


def test_full_text_contains_section_capture_rule(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        TexasStatutesAdapter,
        recording_site({"/resources/BC/htm/BC.503.htm": fixture_text("ustx_BC.503.htm")}, []),
    )
    text = adapter.full_text("BC.503")
    assert "CAPTURE OR USE OF BIOMETRIC IDENTIFIER" in text
    assert "<" not in text


def test_politeness_declares_conservative_delay() -> None:
    assert TexasStatutesAdapter.crawl_delay_seconds == 2.0
    assert "Texas" in TexasStatutesAdapter.license_note
