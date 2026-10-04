"""Korea DRF adapter tests, offline against the documented XML shape.

The fixture follows the official Open API specification for
``lawSearch.do?target=law&type=XML`` (Korean-named tags); it also
exercises the English-title fallback and an entry without an id.
"""

from __future__ import annotations

import pytest

from open_law.fetcher import RobotDeniedError
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.kr import KoreaLawAdapter
from tests.helpers import FixtureLoader, Offline, RecordingSite

_LAWS_URL = "https://www.law.go.kr/DRF/lawSearch.do"


def test_search_without_key_explains_registration(
    monkeypatch: pytest.MonkeyPatch, offline: Offline, recording_site: RecordingSite
) -> None:
    monkeypatch.delenv("LAW_KR_OC", raising=False)
    adapter = offline(KoreaLawAdapter, recording_site({}, []))
    with pytest.raises(NotAvailableBySourceError, match="LAW_KR_OC"):
        adapter.search("은행법")


def test_search_parses_documented_xml(
    monkeypatch: pytest.MonkeyPatch,
    offline: Offline,
    recording_site: RecordingSite,
    fixture_text: FixtureLoader,
) -> None:
    monkeypatch.setenv("LAW_KR_OC", "testkey")
    seen: list[str] = []
    adapter = offline(
        KoreaLawAdapter,
        recording_site({"/DRF/lawSearch.do": fixture_text("kr_lawsearch_bank.xml")}, seen),
    )
    results = adapter.search("은행법")
    # The id-less entry is skipped; the English-titled entry falls back.
    assert len(results) == 3
    first = results[0]
    assert first.source == "kr"
    assert first.jurisdiction == "KR"
    assert first.law_id == "001653"
    assert first.title == "은행법"
    assert first.promulgation_date == "2025-03-18"
    assert ("promulgation_date_raw", "20250318") in first.extras
    assert first.url == "https://law.go.kr/LSW/lawInfo.do?법령ID=001653"
    # The empty 약칭명 tag yields no extras; the filled one does.
    assert ("abbreviation", "은행법시행령") in results[1].extras
    assert ("category", "대통령령") in results[1].extras
    assert first.extras != () and results[2].title == "English-named entry"
    requested = [url for url in seen if "lawSearch.do" in url]
    assert requested == [(f"{_LAWS_URL}?target=law&type=XML&query=%EC%9D%80%ED%96%89%EB%B2%95&OC=testkey")]


def test_search_clamps_limit(
    monkeypatch: pytest.MonkeyPatch, offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    monkeypatch.setenv("LAW_KR_OC", "testkey")
    adapter = offline(
        KoreaLawAdapter,
        recording_site({"/DRF/lawSearch.do": fixture_text("kr_lawsearch_bank.xml")}, []),
    )
    assert len(adapter.search("은행법", limit=0)) == 1


def test_search_malformed_xml_raises(
    monkeypatch: pytest.MonkeyPatch, offline: Offline, recording_site: RecordingSite
) -> None:
    monkeypatch.setenv("LAW_KR_OC", "testkey")
    adapter = offline(KoreaLawAdapter, recording_site({"/DRF/lawSearch.do": "<not-xml"}, []))
    with pytest.raises(ValueError, match="malformed XML"):
        adapter.search("은행법")


def test_search_without_laws_element_returns_empty(
    monkeypatch: pytest.MonkeyPatch, offline: Offline, recording_site: RecordingSite
) -> None:
    monkeypatch.setenv("LAW_KR_OC", "testkey")
    adapter = offline(KoreaLawAdapter, recording_site({"/DRF/lawSearch.do": "<LawSearch/>"}, []))
    assert adapter.search("nothing") == []


def test_fetch_points_at_lawservice(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(KoreaLawAdapter, recording_site({}, []))
    with pytest.raises(NotAvailableBySourceError, match=r"lawService\.do"):
        adapter.fetch("001653")


def test_robots_disallow_blocks_search(
    monkeypatch: pytest.MonkeyPatch, offline: Offline, recording_site: RecordingSite
) -> None:
    monkeypatch.setenv("LAW_KR_OC", "testkey")
    adapter = offline(
        KoreaLawAdapter,
        recording_site({}, [], robots="User-agent: *\nDisallow: /\n"),
    )
    with pytest.raises(RobotDeniedError):
        adapter.search("은행법")
