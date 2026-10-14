"""e-Gov v2 adapter tests, offline against the captured JSON."""

from __future__ import annotations


import pytest

from tests.helpers import FixtureLoader, Offline, RecordingSite

from open_law.sources.jp import EgovAdapter

_LAWS_URL = "https://laws.e-gov.go.jp/api/2/laws"


def test_search_parses_law_list_json(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        EgovAdapter,
        recording_site({"/api/2/laws": fixture_text("egov_search_bankin.json")}, seen),
    )
    results = adapter.search("銀行法")
    assert len(results) == 3
    first = results[0]
    assert first.source == "jp"
    assert first.jurisdiction == "JP"
    assert first.law_id == "325AC0000000041"
    assert first.title == "日本勧業銀行法等を廃止する法律"
    assert first.promulgation_date == "1950-03-31"
    assert first.url == "https://laws.e-gov.go.jp/document?law_id=325AC0000000041"
    assert first.extras["law_num"] == "昭和二十五年法律第四十一号"
    assert first.extras["law_title_kana"] == "にほんかんぎょうぎんこうほうとうをはいしするほうりつ"
    assert first.extras["category"] == "金融・保険"
    assert f"{_LAWS_URL}?law_title=%E9%8A%80%E8%A1%8C%E6%B3%95&limit=10" in seen


def test_search_clamps_limit_to_at_least_one(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        EgovAdapter,
        recording_site({"/api/2/laws": fixture_text("egov_search_bankin.json")}, seen),
    )
    adapter.search("銀行法", limit=0)
    assert any("limit=1" in url for url in seen)


def test_search_malformed_json_raises(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EgovAdapter, recording_site({"/api/2/laws": "definitely { not json"}, []))
    with pytest.raises(ValueError, match="malformed JSON"):
        adapter.search("銀行法")


def test_search_non_object_body_raises(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EgovAdapter, recording_site({"/api/2/laws": "[1, 2, 3]"}, []))
    with pytest.raises(ValueError, match="non-object"):
        adapter.search("銀行法")


def test_search_skips_unusable_entries(offline: Offline, recording_site: RecordingSite) -> None:
    junk = (
        '{"laws": ["a string entry", {"revision_info": {"law_title": "no law_id"}}, '
        '{"law_info": {"law_id": "1", "law_num": "第一条"}, '
        '"revision_info": {"law_title": "数字だけの法令", "law_title_kana": null, '
        '"category": null}}]}'
    )
    adapter = offline(EgovAdapter, recording_site({"/api/2/laws": junk}, []))
    results = adapter.search("test")
    assert len(results) == 1
    assert results[0].law_id == "1"
    assert results[0].title == "数字だけの法令"
    assert results[0].extras == {"law_num": "第一条"}


def test_search_without_laws_field_returns_empty(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EgovAdapter, recording_site({"/api/2/laws": '{"total_count": 0}'}, []))
    assert adapter.search("nothing") == []


def test_fetch_parses_v1_lawdata_without_registration(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        EgovAdapter,
        recording_site(
            {
                "/api/1/lawdata/325AC0000000041": fixture_text("egov_lawdata_325AC0000000041.xml"),
                "/api/2/laws": fixture_text("egov_search_bankin.json"),
            },
            seen,
        ),
    )
    law = adapter.fetch("325AC0000000041")
    assert law.source == "jp"
    assert law.jurisdiction == "JP"
    assert law.law_id == "325AC0000000041"
    assert law.title == "日本勧業銀行法等を廃止する法律"
    assert law.promulgation_date == "1950-03-31"
    # The v2 revision_info stamps the enactment's own date as its
    # "amendment" — never amended, so last_amended is None, never a date
    # equal to promulgation. consolidated_as_of is the v2 enforcement date.
    assert law.last_amended is None
    assert law.consolidated_as_of == "1950-03-31"
    assert law.url == "https://laws.e-gov.go.jp/document?law_id=325AC0000000041"
    assert law.language == "jpn"
    assert law.text_url == "https://laws.e-gov.go.jp/api/1/lawdata/325AC0000000041"
    assert law.extras["format"] == "egov-law-xml"
    assert law.extras["law_type"] == "Act"
    assert law.extras["era"] == "Showa"
    assert seen == [
        "https://laws.e-gov.go.jp/robots.txt",
        "https://laws.e-gov.go.jp/api/1/lawdata/325AC0000000041",
        "https://laws.e-gov.go.jp/api/2/laws?law_id=325AC0000000041&limit=1",
    ]


def test_fetch_unknown_id_raises(offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader) -> None:
    adapter = offline(
        EgovAdapter, recording_site({"/api/1/lawdata/999AC0000000000": fixture_text("egov_lawdata_unknown.xml")}, [])
    )
    with pytest.raises(ValueError, match="no law"):
        adapter.fetch("999AC0000000000")


def test_fetch_rejects_malformed_id(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EgovAdapter, recording_site({}, []))
    with pytest.raises(ValueError, match="Unrecognised e-Gov law id"):
        adapter.fetch("not-an-id!!!")
