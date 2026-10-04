"""eCFR adapter tests, offline against captured API responses.

Fixtures are trimmed copies of real eCFR API responses (search JSON and
full-XML), keeping the on-wire shape faithful: query-highlight markup in
headings, ``hierarchy``/``headings``/``hierarchy_headings`` triple, and the
``<DIV8 ...><HEAD>`` full-text envelope.
"""

from __future__ import annotations

import datetime as dt

import pytest

from open_law.fetcher import RobotDeniedError
from open_law.sources.us import EcfrAdapter
from tests.helpers import FixtureLoader, Offline, RecordingSite

_SEARCH_URL = "https://www.ecfr.gov/api/search/v1/results"


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def test_search_maps_hierarchy_to_ecfr_paths(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        EcfrAdapter,
        recording_site({"/api/search/v1/results": fixture_text("ecfr_search_copyright.json")}, seen),
    )
    results = adapter.search("copyright")
    assert len(results) == 2

    section = results[0]
    assert section.source == "us"
    assert section.jurisdiction == "US"
    assert section.law_id == "title-37/section-202.2"
    assert section.title == "Copyright notice."
    assert section.promulgation_date == "2017-09-12"
    assert section.url == "https://www.ecfr.gov/current/title-37/section-202.2"
    assert ("node_type", "Section") in section.extras
    assert ("change_types", "cross_reference") in section.extras

    part = results[1]
    assert part.law_id == "title-16/part-312"
    assert part.title == "Children's Online Privacy Protection Rule"
    assert ("node_type", "Part") in part.extras

    requested = [u for u in seen if "search/v1/results" in u]
    assert requested == [f"{_SEARCH_URL}?query=copyright&per_page=10"]


def test_search_clamps_limit(offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader) -> None:
    adapter = offline(
        EcfrAdapter,
        recording_site({"/api/search/v1/results": fixture_text("ecfr_search_copyright.json")}, []),
    )
    assert len(adapter.search("copyright", limit=0)) >= 1


def test_search_malformed_json_raises(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EcfrAdapter, recording_site({"/api/search/v1/results": "not json"}, []))
    with pytest.raises(ValueError, match="malformed JSON"):
        adapter.search("anything")


def test_search_empty_results_returns_empty(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EcfrAdapter, recording_site({"/api/search/v1/results": '{"results":[]}'}, []))
    assert adapter.search("nothing") == []


def test_fetch_section_returns_law_with_head_title(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        EcfrAdapter,
        recording_site({f"/api/versioner/v1/full/{_today()}/title-16.xml": fixture_text("ecfr_t16_s312_5.xml")}, []),
    )
    law = adapter.fetch("title-16/part-312/section-312.5")
    assert law.law_id == "title-16/part-312/section-312.5"
    assert law.title == "§ 312.5 Parental consent."
    assert law.language == "eng"
    assert law.text_url is not None and "part=312" in law.text_url and "section=312.5" in law.text_url
    assert ("format", "ecfr-xml") in law.extras


def test_fetch_unrecognised_node_raises(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EcfrAdapter, recording_site({}, []))
    with pytest.raises(ValueError, match="unrecognised eCFR node"):
        adapter.fetch("uscode-title17")


def test_fetch_part_scopes_part_param(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        EcfrAdapter,
        recording_site({f"/api/versioner/v1/full/{_today()}/title-16.xml": fixture_text("ecfr_t16_s312_5.xml")}, seen),
    )
    adapter.fetch("title-16/part-312")
    requested = [u for u in seen if "versioner/v1/full" in u]
    assert len(requested) == 1 and "part=312" in requested[0] and "section=" not in requested[0]


def test_robots_disallow_blocks_search(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(
        EcfrAdapter,
        recording_site(
            {"/api/search/v1/results": "{}"},
            [],
            robots="User-agent: *\nDisallow: /\n",
        ),
    )
    with pytest.raises(RobotDeniedError):
        adapter.search("copyright")
