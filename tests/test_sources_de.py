"""Germany Gesetze-im-Internet adapter tests, offline against captured pages."""

from __future__ import annotations

import pytest

from tests.helpers import FixtureLoader, Offline, RecordingSite

from open_law.sources.de import GesetzeImInternetAdapter


def test_search_finds_bgb_by_abbreviation(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        GesetzeImInternetAdapter,
        recording_site({"/Teilliste_B.html": fixture_text("de_teilb_excerpt.html")}, seen),
    )
    results = adapter.search("BGB")
    assert len(results) == 1
    first = results[0]
    assert first.source == "de"
    assert first.jurisdiction == "DE"
    assert first.law_id == "bgb"
    assert first.title == "Bürgerliches Gesetzbuch"
    assert first.url == "https://www.gesetze-im-internet.de/bgb/index.html"
    assert first.extras["abbrev"] == "BGB"
    assert "https://www.gesetze-im-internet.de/Teilliste_B.html" in seen


def test_search_matches_full_title_case_insensitively(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        GesetzeImInternetAdapter,
        recording_site({"/Teilliste_B.html": fixture_text("de_teilb_excerpt.html")}, []),
    )
    results = adapter.search("bürgerliches gesetzbuch")
    assert [r.law_id for r in results] == ["bgb"]


def test_search_respects_limit(offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader) -> None:
    adapter = offline(
        GesetzeImInternetAdapter,
        recording_site({"/Teilliste_B.html": fixture_text("de_teilb_excerpt.html")}, []),
    )
    assert len(adapter.search("B", limit=1)) == 1


def test_search_without_letters_returns_empty(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(GesetzeImInternetAdapter, recording_site({}, []))
    assert adapter.search("123") == []


def test_fetch_resolves_full_html_text_url(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        GesetzeImInternetAdapter,
        recording_site({"/baasaareinfdv/index.html": fixture_text("de_baasaareinfdv_index.html")}, seen),
    )
    law = adapter.fetch("baasaareinfdv")
    assert law.source == "de"
    assert law.law_id == "baasaareinfdv"
    assert law.title == (
        "Rechtsverordnung des Präsidenten des Bundesausgleichsamtes zur Einführung von Rechtsverordnungen im Saarland"
    )
    assert law.extras["format"] == "gii-html"
    assert seen == [
        "https://www.gesetze-im-internet.de/robots.txt",
        "https://www.gesetze-im-internet.de/baasaareinfdv/index.html",
    ]


def test_fetch_rejects_non_folder_id(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(GesetzeImInternetAdapter, recording_site({}, []))
    with pytest.raises(ValueError, match="Unrecognised Gesetze-im-Internet id"):
        adapter.fetch("not a folder!!!")


def test_fetch_without_full_html_falls_back_to_index(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        GesetzeImInternetAdapter,
        recording_site({"/bgb/index.html": fixture_text("de_teilb_excerpt.html")}, []),
    )
    # The Teilliste excerpt has no Gesamtausgabe block: text_url falls back to the page itself.
    law = adapter.fetch("bgb")
    assert law.text_url == "https://www.gesetze-im-internet.de/bgb/index.html"


def test_full_text_strips_to_plain_text(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        GesetzeImInternetAdapter,
        recording_site(
            {
                "/baasaareinfdv/index.html": fixture_text("de_baasaareinfdv_index.html"),
                "/baasaareinfdv/BJNR505500961.html": fixture_text("de_baasaareinfdv_index.html"),
            },
            [],
        ),
    )
    text = adapter.full_text("baasaareinfdv")
    assert "Rechtsverordnung des Präsidenten" in text
    assert "Feedback-Formular" in text


def test_politeness_declares_conservative_delay() -> None:
    assert GesetzeImInternetAdapter.crawl_delay_seconds == 2.0
    assert "federal statutes" in GesetzeImInternetAdapter.license_note
