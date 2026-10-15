"""EU CELLAR adapter tests, offline against the captured RDF and XHTML."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.helpers import FixtureLoader, Handler, Offline, RecordingSite

from open_law.fetcher import FetchConfig
from open_law.fetcher import PoliteFetcher
from open_law.sources.adapter import NotAvailableBySourceError
from open_law.sources.eu import EurlexAdapter

_CELEX_URL = "https://publications.europa.eu/resource/celex/32022R2065"
_XHTML_URL = "https://publications.europa.eu/resource/celex/32022R2065.ENG.xhtml"


def _eu_site(
    recording_site: RecordingSite,
    seen: list[str],
    rdf: str,
    xhtml: str | None,
) -> Handler:
    """Fake CELLAR: RDF metadata plus the XHTML rendition (or its 404)."""
    responses = {"/resource/celex/32022R2065": rdf}
    if xhtml is not None:
        responses["/resource/celex/32022R2065.ENG.xhtml"] = xhtml
    return recording_site(responses, seen)


def _wired(handler: Handler, cache_dir: Path) -> EurlexAdapter:
    """Adapter on a mock-transport fetcher carrying the declared negotiation headers.

    ``default_fetcher`` passes ``http_headers`` to the fetcher; the shared
    ``offline`` fixture injects a bare client, so header-sensitive tests
    build the same wiring themselves.
    """
    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = FetchConfig(cache_dir=cache_dir, delay_seconds=0)
    return EurlexAdapter(PoliteFetcher(config, client=client, headers=dict(EurlexAdapter.http_headers)))


def test_fetch_parses_cellar_rdf(offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader) -> None:
    seen: list[str] = []
    adapter = offline(
        EurlexAdapter,
        _eu_site(
            recording_site,
            seen,
            fixture_text("eu_celex_32022R2065.rdf"),
            fixture_text("eu_celex_32022R2065_articles.xhtml"),
        ),
    )
    law = adapter.fetch("32022R2065")
    assert law.source == "eu"
    assert law.jurisdiction == "EU"
    assert law.law_id == "32022R2065"
    assert "Digital Services Act" in law.title
    assert law.language == "ENG"
    assert law.last_amended is None
    assert law.consolidated_as_of == "2023-12-13"
    assert law.url == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R2065"
    assert law.text_url == _CELEX_URL
    assert law.extras["celex"] == "32022R2065"
    assert law.extras["resource_type"] == "expression"
    assert law.extras["title_short"] == "DSA, Digital Services Act, DSA Regulation"
    assert [provision.id for provision in law.provisions] == ["art_1", "art_2", "art_8"]
    first = law.provisions[0]
    assert first.num == "Article 1"
    assert first.heading == "Subject matter"
    assert [child.id for child in first.children] == ["art_1__para_1", "art_1__para_2"]
    assert "proper functioning of the internal market" in first.children[0].text
    assert [item.num for item in first.children[1].children] == ["(a)", "(b)"]
    assert seen == ["https://publications.europa.eu/robots.txt", _CELEX_URL, _XHTML_URL]


def test_fetch_missing_xhtml_leaves_provisions_empty(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """A 404 rendition is not a failed fetch: metadata still lands, provisions stay empty."""
    seen: list[str] = []
    adapter = offline(
        EurlexAdapter,
        _eu_site(recording_site, seen, fixture_text("eu_celex_32022R2065.rdf"), None),
    )
    law = adapter.fetch("32022R2065")
    assert "Digital Services Act" in law.title
    assert law.provisions == ()
    assert seen == ["https://publications.europa.eu/robots.txt", _CELEX_URL, _XHTML_URL]


def test_fetch_malformed_xhtml_raises(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        EurlexAdapter,
        _eu_site(recording_site, [], fixture_text("eu_celex_32022R2065.rdf"), "<html:broken"),
    )
    with pytest.raises(ValueError, match="malformed XHTML"):
        adapter.fetch("32022R2065")


def test_fetch_malformed_rdf_raises(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EurlexAdapter, recording_site({"/resource/celex/32022R2065": "<rdf:broken"}, []))
    with pytest.raises(ValueError, match="malformed RDF"):
        adapter.fetch("32022R2065")


def test_fetch_without_titles_falls_back_to_celex(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    bare = (
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="urn:x"/></rdf:RDF>'
    )
    adapter = offline(
        EurlexAdapter,
        _eu_site(recording_site, [], bare, fixture_text("eu_celex_32022R2065_articles.xhtml")),
    )
    law = adapter.fetch("32022R2065")
    assert law.title == "32022R2065"
    assert law.extras == {"celex": "32022R2065"}
    assert [provision.id for provision in law.provisions] == ["art_1", "art_2", "art_8"]


def test_search_points_at_sparql(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EurlexAdapter, recording_site({}, []))
    with pytest.raises(NotAvailableBySourceError, match="SPARQL"):
        adapter.search("data act", limit=3)


def test_xhtml_request_negotiates_its_own_accept(
    tmp_path: Path, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """The rendition override never leaks into the metadata request (or vice versa)."""
    accepts: dict[str, str | None] = {}
    site = _eu_site(
        recording_site,
        [],
        fixture_text("eu_celex_32022R2065.rdf"),
        fixture_text("eu_celex_32022R2065_articles.xhtml"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith(".xhtml"):
            accepts["xhtml"] = request.headers.get("Accept")
        elif path != "/robots.txt":
            accepts["rdf"] = request.headers.get("Accept")
        return site(request)

    law = _wired(handler, tmp_path).fetch("32022R2065")
    assert accepts == {"rdf": "application/rdf+xml", "xhtml": "application/xhtml+xml"}
    assert law.provisions[0].id == "art_1"


def test_both_renditions_cache_under_their_own_accept(
    tmp_path: Path, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """A re-fetch is free: RDF and XHTML bodies cache as two distinct entries.

    One shared cache entry would either hand the RDF parser an XHTML body
    (raising) or refetch the rendition on every run, so a second fetch
    that both succeeds and adds no request proves the keys are separate.
    """
    seen: list[str] = []
    handler = _eu_site(
        recording_site,
        seen,
        fixture_text("eu_celex_32022R2065.rdf"),
        fixture_text("eu_celex_32022R2065_articles.xhtml"),
    )
    adapter = _wired(handler, tmp_path)
    first = adapter.fetch("32022R2065")
    second = adapter.fetch("32022R2065")
    assert first.provisions == second.provisions
    assert [p.id for p in second.provisions] == ["art_1", "art_2", "art_8"]
    assert seen == ["https://publications.europa.eu/robots.txt", _CELEX_URL, _XHTML_URL]


def test_content_negotiation_headers_declared() -> None:
    """CELLAR needs Accept/Accept-Language; the adapter declares them."""
    assert EurlexAdapter.http_headers["Accept"] == "application/rdf+xml"
    assert EurlexAdapter.http_headers["Accept-Language"] == "eng"
