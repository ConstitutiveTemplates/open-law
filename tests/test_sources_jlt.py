"""JLT adapter tests, offline against the captured JLT view page.

The fixture is the real ``/en/laws/view/4913`` page trimmed to its
<title> + the download block (TMX/PDF links) — the only parts the
adapter parses. Free-text search is CSRF-gated (verified 2026-10-04:
403 on machines), so search degrades to NotAvailableBySourceError per
the eur-lex/ca precedent.
"""

from __future__ import annotations

import pytest

from open_law.fetcher import RobotDeniedError
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.jlt import JltAdapter
from tests.helpers import FixtureLoader
from tests.helpers import Offline
from tests.helpers import RecordingSite

_VIEW_URL = "https://www.japaneselawtranslation.go.jp/en/laws/view/4913"
_TMX_URL = "https://www.japaneselawtranslation.go.jp/en/laws/download/4913/23/9141.tmx"


def test_fetch_lsa_returns_official_translation(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    seen: list[str] = []
    adapter = offline(
        JltAdapter,
        recording_site({"/en/laws/view/4913": fixture_text("jlt_view_4913.html")}, seen),
    )
    law = adapter.fetch("4913")
    assert law.source == "jlt"
    assert law.jurisdiction == "JP"
    assert law.law_id == "4913"
    assert law.title == "Labor Standards Act"
    assert law.language == "eng"
    assert law.url == _VIEW_URL
    assert law.text_url == _TMX_URL
    assert ("format", "jlt-tmx") in law.extras
    assert ("pdf_url", "https://www.japaneselawtranslation.go.jp/en/laws/download/4913/14/s22Aa000490404je17.0_r2A13.pdf") in law.extras
    assert seen == ["https://www.japaneselawtranslation.go.jp/robots.txt", _VIEW_URL]


def test_fetch_tolerates_prefix_and_whitespace(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    for variant in ("jlt4913", "/4913", "  4913  "):
        adapter = offline(
            JltAdapter,
            recording_site({"/en/laws/view/4913": fixture_text("jlt_view_4913.html")}, []),
        )
        assert adapter.fetch(variant).law_id == "4913"


def test_fetch_unrecognised_id_raises(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(JltAdapter, recording_site({}, []))
    with pytest.raises(ValueError, match="Unrecognised JLT id"):
        adapter.fetch("not-an-id")


def test_fetch_without_tmx_raises(offline: Offline, recording_site: RecordingSite) -> None:
    bare = "<html><head><title>X</title></head><body>no tmx</body></html>"
    adapter = offline(JltAdapter, recording_site({"/en/laws/view/9999": bare}, []))
    with pytest.raises(NotAvailableBySourceError, match="no TMX download"):
        adapter.fetch("9999")


def test_search_points_at_index(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(JltAdapter, recording_site({}, []))
    with pytest.raises(NotAvailableBySourceError, match="CSRF-gated"):
        adapter.search("labor", limit=3)


def test_robots_disallow_blocks_fetch(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    denied = offline(
        JltAdapter,
        recording_site(
            {"/en/laws/view/4913": fixture_text("jlt_view_4913.html")},
            [],
            robots="User-agent: *\nDisallow: /\n",
        ),
    )
    with pytest.raises(RobotDeniedError):
        denied.fetch("4913")
