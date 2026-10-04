"""Canada Justice Laws adapter tests, offline against captured XML.

The fixture is the real ``/eng/XML/P-8.6.xml`` response trimmed to the
<Identification> block — root attributes (pit-date, lastAmendedDate,
in-force) plus both titles stay byte-faithful, which is everything the
adapter parses. Keyword search has no machine endpoint (verified
2026-10-04: Search.aspx returns the empty form), so search degrades to
NotAvailableBySourceError per the eur-lex precedent.
"""

from __future__ import annotations

import pytest

from open_law.fetcher import RobotDeniedError
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.ca import JusticeLawsAdapter
from tests.helpers import FixtureLoader
from tests.helpers import Offline
from tests.helpers import RecordingSite

_XML_URL = "https://laws-lois.justice.gc.ca/eng/XML/P-8.6.xml"


def test_fetch_pipeda_returns_short_title(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        JusticeLawsAdapter,
        recording_site({"/eng/XML/P-8.6.xml": fixture_text("ca_P-8.6.xml")}, seen),
    )
    law = adapter.fetch("P-8.6")
    assert law.source == "ca"
    assert law.jurisdiction == "CA"
    assert law.law_id == "P-8.6"
    assert law.title == "Personal Information Protection and Electronic Documents Act"
    assert law.language == "eng"
    assert law.modified == "2026-03-26"
    assert law.url == "https://laws-lois.justice.gc.ca/eng/acts/P-8.6/"
    assert law.text_url == _XML_URL
    assert ("format", "justice-xml") in law.extras
    assert ("in_force", "yes") in law.extras
    assert ("last_amended", "2025-03-04") in law.extras
    assert seen == ["https://laws-lois.justice.gc.ca/robots.txt", _XML_URL]


def test_fetch_tolerates_suffix_and_prefix(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    for variant in ("p-8.6.xml", "acts/P-8.6", "C46"):
        path = "/eng/XML/P-8.6.xml" if "8.6" in variant else "/eng/XML/C-46.xml"
        adapter = offline(
            JusticeLawsAdapter,
            recording_site({path: fixture_text("ca_P-8.6.xml")}, []),
        )
        law = adapter.fetch(variant)
        assert law.law_id in ("P-8.6", "C-46")


def test_fetch_unrecognised_code_raises(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(JusticeLawsAdapter, recording_site({}, []))
    with pytest.raises(ValueError, match="Unrecognised Justice Laws act code"):
        adapter.fetch("not-a-law!!!")


def test_fetch_without_titles_falls_back_to_code(offline: Offline, recording_site: RecordingSite) -> None:
    bare = '<?xml version="1.0"?><Statute pit-date="2026-01-01"><Identification/></Statute>'
    adapter = offline(JusticeLawsAdapter, recording_site({"/eng/XML/C-46.xml": bare}, []))
    law = adapter.fetch("C-46")
    assert law.title == "C-46"
    assert law.modified == "2026-01-01"


def test_search_points_at_acts_index(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(JusticeLawsAdapter, recording_site({}, []))
    with pytest.raises(NotAvailableBySourceError, match="no machine keyword search"):
        adapter.search("privacy", limit=3)


def test_robots_disallow_without_robots_txt_is_permissive(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    # Justice Laws serves no robots.txt (404): the fetcher treats an absent
    # robots file as allowed — the adapter must still deny when a site does
    # disallow.
    denied = offline(
        JusticeLawsAdapter,
        recording_site(
            {"/eng/XML/P-8.6.xml": fixture_text("ca_P-8.6.xml")},
            [],
            robots="User-agent: *\nDisallow: /\n",
        ),
    )
    with pytest.raises(RobotDeniedError):
        denied.fetch("P-8.6")


def test_politeness_declares_conservative_delay() -> None:
    assert JusticeLawsAdapter.crawl_delay_seconds == 2.0
    assert "Crown copyright" in JusticeLawsAdapter.license_note
