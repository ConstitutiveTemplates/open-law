"""mvlaw adapter tests, offline against captured pages."""

from __future__ import annotations

import pytest

from open_law.fetcher import RobotDeniedError

from open_law.sources.mv import MvLawAdapter
from tests.helpers import FixtureLoader, Offline, RecordingSite

_SHOW_URL = "https://mvlaw.gov.mv/dv/legislations/291"
_TEXT_URL = "https://mvlaw.gov.mv/dv/legislations/291/consolidations/1302"


def test_fetch_parses_consolidation_page(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        MvLawAdapter,
        recording_site({"/dv/legislations/291": fixture_text("mv_consolidation_291_1302.html")}, seen),
    )
    law = adapter.fetch("291")
    extras = dict(law.extras)
    assert law.source == "mv"
    assert law.jurisdiction == "MV"
    assert law.law_id == "291"
    assert law.title == "ޒަކާތުގެ ޤާނޫނު"
    assert law.promulgation_date == "2025-12-06"
    assert law.url == _SHOW_URL
    assert law.language == "div"
    assert law.text_url == _TEXT_URL
    assert extras["legislation_no"] == "27/2025"
    assert extras["consolidation_id"] == "1302"
    assert extras["original_document_url"].endswith(".pdf")
    assert seen == ["https://mvlaw.gov.mv/robots.txt", _SHOW_URL]


def test_fetch_rejects_non_numeric_ids(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(MvLawAdapter, recording_site({}, []))
    with pytest.raises(ValueError, match="not an mvlaw legislation id"):
        adapter.fetch("zakaathuge-aanoonu")


def test_fetch_missing_legislation_raises_lookup(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        MvLawAdapter,
        recording_site({"/dv/legislations/239": fixture_text("mv_legislations_p1.html")}, []),
    )
    with pytest.raises(LookupError, match="no legislation with id"):
        adapter.fetch("239")


def test_search_matches_legislation_number(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        MvLawAdapter,
        recording_site({"/dv/legislations": fixture_text("mv_legislations_p1.html")}, seen),
    )
    results = adapter.search("4/75", limit=1)
    assert [r.law_id for r in results] == ["88"]
    assert results[0].source == "mv"
    assert results[0].jurisdiction == "MV"
    assert results[0].promulgation_date == "1955-09-25"
    assert "https://mvlaw.gov.mv/dv/legislations?page=1" in seen


def test_search_respects_limit(offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader) -> None:
    adapter = offline(
        MvLawAdapter,
        recording_site({"/dv/legislations": fixture_text("mv_legislations_p1.html")}, []),
    )
    assert len(adapter.search("ޤާނޫނުއަސާސީ", limit=2)) == 2


def test_search_blank_query_returns_empty(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(MvLawAdapter, recording_site({}, []))
    assert adapter.search("   ") == []


def test_robots_disallow_blocks_fetch(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        MvLawAdapter,
        recording_site(
            {"/dv/legislations/291": fixture_text("mv_consolidation_291_1302.html")},
            [],
            robots="User-agent: *\nDisallow: /dv/\n",
        ),
    )
    with pytest.raises(RobotDeniedError):
        adapter.fetch("291")


def test_extra_politeness_for_small_government_server() -> None:
    """No robots.txt Crawl-delay exists — the adapter volunteers 2 s."""
    assert MvLawAdapter.crawl_delay_seconds == 2.0


def test_full_text_extracts_section_tree(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        MvLawAdapter,
        recording_site(
            {
                "/dv/legislations/291": fixture_text("mv_consolidation_291_1302.html"),
                "/dv/legislations/291/consolidations/1302": fixture_text("mv_consolidation_291_1302.html"),
            },
            seen,
        ),
    )
    text = adapter.full_text("291")
    assert "ޒަކާތުގެ ޤާނޫނު" in text
    assert "<" not in text
    assert len(text) > 10_000
    assert _TEXT_URL in seen
