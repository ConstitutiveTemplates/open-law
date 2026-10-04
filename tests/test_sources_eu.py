"""EU CELLAR adapter tests, offline against the captured RDF."""

from __future__ import annotations


import pytest

from tests.helpers import FixtureLoader, Offline, RecordingSite

from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.eu import EurlexAdapter

_CELEX_URL = "https://publications.europa.eu/resource/celex/32022R2065"


def test_fetch_parses_cellar_rdf(offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader) -> None:
    seen: list[str] = []
    adapter = offline(
        EurlexAdapter,
        recording_site({"/resource/celex/32022R2065": fixture_text("eu_celex_32022R2065.rdf")}, seen),
    )
    law = adapter.fetch("32022R2065")
    assert law.source == "eu"
    assert law.jurisdiction == "EU"
    assert law.law_id == "32022R2065"
    assert "Digital Services Act" in law.title
    assert law.language == "ENG"
    assert law.modified is not None
    assert law.url == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R2065"
    assert law.text_url == _CELEX_URL
    assert ("celex", "32022R2065") in law.extras
    assert ("resource_type", "expression") in law.extras
    assert ("title_short", "DSA, Digital Services Act, DSA Regulation") in law.extras
    assert seen == ["https://publications.europa.eu/robots.txt", _CELEX_URL]


def test_fetch_malformed_rdf_raises(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EurlexAdapter, recording_site({"/resource/celex/32022R2065": "<rdf:broken"}, []))
    with pytest.raises(ValueError, match="malformed RDF"):
        adapter.fetch("32022R2065")


def test_fetch_without_titles_falls_back_to_celex(offline: Offline, recording_site: RecordingSite) -> None:
    bare = (
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="urn:x"/></rdf:RDF>'
    )
    adapter = offline(EurlexAdapter, recording_site({"/resource/celex/32022R2065": bare}, []))
    law = adapter.fetch("32022R2065")
    assert law.title == "32022R2065"
    assert law.extras == (("celex", "32022R2065"),)


def test_search_points_at_sparql(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EurlexAdapter, recording_site({}, []))
    with pytest.raises(NotAvailableBySourceError, match="SPARQL"):
        adapter.search("data act", limit=3)


def test_content_negotiation_headers_declared() -> None:
    """CELLAR needs Accept/Accept-Language; the adapter declares them."""
    assert EurlexAdapter.http_headers["Accept"] == "application/rdf+xml"
    assert EurlexAdapter.http_headers["Accept-Language"] == "eng"
