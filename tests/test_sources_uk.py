"""legislation.gov.uk adapter tests, offline against the captured XML."""

from __future__ import annotations


import pytest

from tests.helpers import FixtureLoader, Offline, RecordingSite

from open_law.fetcher import RobotDeniedError
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.uk import LegislationGovUkAdapter

_DATA_XML = "/ukcm/2023/1/data.xml"


def test_fetch_parses_metadata_xml(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        LegislationGovUkAdapter,
        recording_site({_DATA_XML: fixture_text("uk_ukcm_2023_1_data.xml")}, seen),
    )
    law = adapter.fetch("ukcm/2023/1")
    assert law.source == "uk"
    assert law.jurisdiction == "GB"
    assert law.law_id == "ukcm/2023/1"
    assert law.title == "Diocesan Stipends Funds (Amendment) Measure 2023"
    assert law.language == "en"
    assert law.modified == "2023-11-23"
    assert law.url == "http://www.legislation.gov.uk/ukcm/2023/1"
    assert law.text_url == "https://www.legislation.gov.uk/ukcm/2023/1/data.xml"
    assert law.akn_url == "https://www.legislation.gov.uk/ukcm/2023/1/data.akn"
    assert ("legislation_type", "Primary") in law.extras
    assert ("provisions", "3") in law.extras
    assert ("publisher", "Statute Law Database") in law.extras
    assert seen == [
        "https://www.legislation.gov.uk/robots.txt",
        "https://www.legislation.gov.uk" + _DATA_XML,
    ]


def test_fetch_tolerates_surrounding_slashes(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        LegislationGovUkAdapter,
        recording_site({_DATA_XML: fixture_text("uk_ukcm_2023_1_data.xml")}, seen),
    )
    law = adapter.fetch("/ukcm/2023/1/")
    assert law.law_id == "ukcm/2023/1"
    assert "https://www.legislation.gov.uk" + _DATA_XML in seen


def test_fetch_malformed_xml_raises(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(
        LegislationGovUkAdapter,
        recording_site({_DATA_XML: "<not-xml at all"}, []),
    )
    with pytest.raises(ValueError, match="malformed XML"):
        adapter.fetch("ukcm/2023/1")


def test_fetch_without_metadata_falls_back_to_url(offline: Offline, recording_site: RecordingSite) -> None:
    bare = '<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"><Primary></Primary></Legislation>'
    adapter = offline(LegislationGovUkAdapter, recording_site({_DATA_XML: bare}, []))
    law = adapter.fetch("ukcm/2023/1")
    assert law.title == law.text_url
    assert ("legislation_type", "Primary") in law.extras
    assert ("provisions", "3") not in law.extras


def test_fetch_empty_root_has_no_extras(offline: Offline, recording_site: RecordingSite) -> None:
    empty = '<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"/>'
    adapter = offline(LegislationGovUkAdapter, recording_site({_DATA_XML: empty}, []))
    law = adapter.fetch("ukcm/2023/1")
    assert law.title == law.text_url
    assert law.extras == ()


def test_search_is_not_offered(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(LegislationGovUkAdapter, recording_site({}, []))
    with pytest.raises(NotAvailableBySourceError, match="no machine search"):
        adapter.search("banks")


def test_robots_disallow_blocks_fetch(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        LegislationGovUkAdapter,
        recording_site(
            {_DATA_XML: fixture_text("uk_ukcm_2023_1_data.xml")},
            [],
            robots="User-agent: *\nDisallow: /\n",
        ),
    )
    with pytest.raises(RobotDeniedError):
        adapter.fetch("ukcm/2023/1")


def test_politeness_mirrors_robots_crawl_delay() -> None:
    """robots.txt asks Crawl-delay: 5 — the adapter's default delay says 5."""
    assert LegislationGovUkAdapter.crawl_delay_seconds == 5.0
    assert "Open Government Licence" in LegislationGovUkAdapter.license_note


def test_full_text_extracts_xml_character_data(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        LegislationGovUkAdapter,
        recording_site({_DATA_XML: fixture_text("uk_ukcm_2023_1_data.xml")}, []),
    )
    body = adapter.full_text("ukcm/2023/1")
    assert "Diocesan Stipends" in body
    assert "<" not in body
