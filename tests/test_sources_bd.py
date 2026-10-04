"""bdlaws adapter tests, offline against the captured act page."""

from __future__ import annotations

import pytest

from open_law.fetcher import RobotDeniedError
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.bd import BangladeshLawsAdapter
from tests.helpers import FixtureLoader, Offline, RecordingSite

_ACT_URL = "https://bdlaws.minlaw.gov.bd/act-details-43.html"


def test_fetch_parses_act_page(offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader) -> None:
    seen: list[str] = []
    adapter = offline(
        BangladeshLawsAdapter,
        recording_site({"/act-details-43.html": fixture_text("bd_act_43.html")}, seen),
    )
    law = adapter.fetch("43")
    extras = dict(law.extras)
    assert law.source == "bd"
    assert law.jurisdiction == "BD"
    assert law.law_id == "43"
    assert law.title == "The Kazis Act, 1880"
    assert law.language == "en"
    assert law.url == _ACT_URL
    assert law.text_url == _ACT_URL
    assert extras["act_number"] == "43"
    assert extras["year"] == "1880"
    assert extras["preamble"].startswith("An Act")
    assert seen == ["https://bdlaws.minlaw.gov.bd/robots.txt", _ACT_URL]


def test_fetch_accepts_full_page_names(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        BangladeshLawsAdapter,
        recording_site({"/act-details-43.html": fixture_text("bd_act_43.html")}, seen),
    )
    law = adapter.fetch("act-details-43.html")
    assert law.law_id == "43"
    assert _ACT_URL in seen


def test_fetch_rejects_non_numeric_ids(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(BangladeshLawsAdapter, recording_site({}, []))
    with pytest.raises(ValueError, match="not a bdlaws act id"):
        adapter.fetch("kazis-act")


def test_fetch_missing_act_raises_lookup(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(
        BangladeshLawsAdapter,
        recording_site({"/act-details-999999.html": "<title>404</title>"}, []),
    )
    with pytest.raises(LookupError, match="no act with id"):
        adapter.fetch("999999")


def test_search_is_not_offered(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(BangladeshLawsAdapter, recording_site({}, []))
    with pytest.raises(NotAvailableBySourceError, match="no machine search"):
        adapter.search("kazis")


def test_robots_disallow_blocks_fetch(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        BangladeshLawsAdapter,
        recording_site(
            {"/act-details-43.html": fixture_text("bd_act_43.html")},
            [],
            robots="User-agent: *\nDisallow: /\n",
        ),
    )
    with pytest.raises(RobotDeniedError):
        adapter.fetch("43")


def test_extra_politeness_for_small_government_server() -> None:
    """No robots.txt Crawl-delay exists — the adapter volunteers 2 s."""
    assert BangladeshLawsAdapter.crawl_delay_seconds == 2.0


def test_full_text_extracts_act_page(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        BangladeshLawsAdapter,
        recording_site({"/act-details-43.html": fixture_text("bd_act_43.html")}, []),
    )
    body = adapter.full_text("43")
    assert "Kazi" in body
    assert "<" not in body
