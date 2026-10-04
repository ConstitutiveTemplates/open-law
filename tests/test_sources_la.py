"""Lao Official Gazette adapter tests, offline against the captured page."""

from __future__ import annotations

import pytest

from open_law.fetcher import RobotDeniedError
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.la import LaoGazetteAdapter
from tests.helpers import FixtureLoader, Offline, RecordingSite

_DISPLAY_URL = "https://laoofficialgazette.gov.la/index.php?r=site/display&id=2143"


def test_fetch_parses_labeled_rows(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        LaoGazetteAdapter,
        recording_site({"/index.php": fixture_text("la_display_2143.html")}, seen),
    )
    law = adapter.fetch("2143")
    assert law.source == "la"
    assert law.jurisdiction == "LA"
    assert law.law_id == "2143"
    assert law.title.startswith("ຂໍ້ຕົກລົງວ່າດ້ວຍ")
    assert law.language == "lo"
    assert law.url == _DISPLAY_URL
    assert law.text_url is not None and law.text_url.endswith(".pdf")
    assert law.promulgation_date == "2023-10-17"  # ISO; raw DD-MM-YYYY stays in extras
    extras = dict(law.extras)
    assert extras["document_type"] == "ຂໍ້ຕົກລົງ"
    assert "ກະຊວງ" in extras["issued_by"]
    assert extras["document_date"] == "17-10-2023"
    assert extras["gazette_date"] == "01-11-2023"
    assert seen[-1] == _DISPLAY_URL


def test_fetch_accepts_surrounding_text(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        LaoGazetteAdapter,
        recording_site({"/index.php": fixture_text("la_display_2143.html")}, []),
    )
    law = adapter.fetch("display&id=2143")
    assert law.law_id == "2143"


def test_fetch_rejects_non_numeric_ids(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(LaoGazetteAdapter, recording_site({}, []))
    with pytest.raises(ValueError, match="not a Laogazette display id"):
        adapter.fetch("rubber-agreement")


def test_fetch_static_page_raises_lookup(offline: Offline, recording_site: RecordingSite) -> None:
    """The id=12-style 'about' pages have no labeled rows: not a law."""
    static_page = "<title>Laogazette - Display Site</title><h1>ກ່ຽວກັບ ເວັບໄຊນີ້</h1>"
    adapter = offline(
        LaoGazetteAdapter,
        recording_site({"/index.php": static_page}, []),
    )
    with pytest.raises(LookupError, match="not a legal document"):
        adapter.fetch("12")


def test_search_is_not_offered(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(LaoGazetteAdapter, recording_site({}, []))
    with pytest.raises(NotAvailableBySourceError, match="no machine search"):
        adapter.search("ກົດໝາຍ")


def test_robots_disallow_blocks_fetch(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        LaoGazetteAdapter,
        recording_site(
            {"/index.php": fixture_text("la_display_2143.html")},
            [],
            robots="User-agent: *\nDisallow: /\n",
        ),
    )
    with pytest.raises(RobotDeniedError):
        adapter.fetch("2143")


def test_full_text_refuses_pdf_sources(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        LaoGazetteAdapter,
        recording_site({"/index.php": fixture_text("la_display_2143.html")}, []),
    )
    with pytest.raises(NotAvailableBySourceError, match="is a PDF"):
        adapter.full_text("2143")
