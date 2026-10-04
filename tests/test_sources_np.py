"""Nepal Law Commission adapter tests, offline against the captured page."""

from __future__ import annotations

import pytest

from open_law.fetcher import RobotDeniedError
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.np import NepalLawCommissionAdapter
from tests.helpers import FixtureLoader, Offline, RecordingSite

_ACT_URL = "https://lawcommission.gov.np/content/13535/"


def test_fetch_parses_act_page(offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader) -> None:
    seen: list[str] = []
    adapter = offline(
        NepalLawCommissionAdapter,
        recording_site({"/content/13535/": fixture_text("np_act_page.html")}, seen),
    )
    law = adapter.fetch("13535")
    assert law.source == "np"
    assert law.jurisdiction == "NP"
    assert law.law_id == "13535"
    assert law.title == "राष्‍ट्र ऋण उठाउने ऐन, २०८२"
    assert law.url == _ACT_URL
    assert law.text_url == _ACT_URL
    assert law.extras == (("content_id", "13535"),)
    assert seen == ["https://lawcommission.gov.np/robots.txt", _ACT_URL]


def test_fetch_accepts_content_paths(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        NepalLawCommissionAdapter,
        recording_site({"/content/13535/": fixture_text("np_act_page.html")}, seen),
    )
    law = adapter.fetch("/content/13535/national-debt-recovery-act--2082/")
    assert law.law_id == "13535"
    assert _ACT_URL in seen


def test_fetch_title_falls_back_to_site_suffixed_title(offline: Offline, recording_site: RecordingSite) -> None:
    bare = "<title>ऐन कार्यविधि | Nepal Law Commission</title>"
    adapter = offline(
        NepalLawCommissionAdapter,
        recording_site({"/content/13535/": bare}, []),
    )
    law = adapter.fetch("13535")
    assert law.title == "ऐन कार्यविधि"


def test_fetch_rejects_non_numeric_ids(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(NepalLawCommissionAdapter, recording_site({}, []))
    with pytest.raises(ValueError, match="not a Nepal Law Commission content id"):
        adapter.fetch("debt-act")


def test_fetch_missing_content_raises_lookup(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(
        NepalLawCommissionAdapter,
        recording_site({"/content/999999/": "<title>404</title>"}, []),
    )
    with pytest.raises(LookupError, match="no content with id"):
        adapter.fetch("999999")


def test_search_is_not_offered(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(NepalLawCommissionAdapter, recording_site({}, []))
    with pytest.raises(NotAvailableBySourceError, match="no machine search"):
        adapter.search("ऐन")


def test_robots_disallow_blocks_fetch(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        NepalLawCommissionAdapter,
        recording_site(
            {"/content/13535/": fixture_text("np_act_page.html")},
            [],
            robots="User-agent: *\nDisallow: /\n",
        ),
    )
    with pytest.raises(RobotDeniedError):
        adapter.fetch("13535")


def test_politeness_mirrors_robots_crawl_delay() -> None:
    """robots.txt asks Crawl-delay: 10 — the adapter's default delay says 10."""
    assert NepalLawCommissionAdapter.crawl_delay_seconds == 10.0
