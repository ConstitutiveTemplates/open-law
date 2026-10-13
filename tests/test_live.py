"""Live probes: one cheap fetch per registered adapter, opt-in only.

Skipped unless ``OPEN_LAW_LIVE=1``. Run explicitly with
``uv run pytest -m live -q``. Default ``-m "not live"`` excludes them;
without the env they are also skipped via ``pytest.skip``.
"""

from __future__ import annotations

import os

import pytest

from open_law.sources import ADAPTERS
from open_law.sources import open_adapter

# Cheap, stable ids verified against captured fixtures and the live
# endpoints (small pages, ~one request each).
_LIVE_IDS: dict[str, str] = {
    "bd": "43",
    "ca": "P-8.6",
    "de": "bgb",
    "eu": "32022R2065",
    "jlt": "4913",
    "jp": "325AC0000000041",
    "kr": "2100000000000",  # dummy — skipped unless LAW_KR_OC is set
    "la": "2143",
    "mv": "291",
    "uk": "ukcm/2023/1",
    "us": "title-16/part-312/section-312.5",
    "us-tx": "BC.503",
}


@pytest.mark.live
@pytest.mark.parametrize("source_id", sorted(ADAPTERS))
def test_live_fetch_one_per_adapter(source_id: str) -> None:
    """One live fetch per adapter; skipped unless OPEN_LAW_LIVE=1."""
    if os.environ.get("OPEN_LAW_LIVE") != "1":
        pytest.skip("OPEN_LAW_LIVE!=1 — live probes are opt-in")
    if source_id == "kr" and not os.environ.get("LAW_KR_OC"):
        pytest.skip("LAW_KR_OC not set — kr live probe needs an open-API id")
    law_id = _LIVE_IDS.get(source_id)
    if law_id is None:
        pytest.skip(f"no live probe id for source {source_id!r}")
    adapter = open_adapter(source_id)
    # Keep live probes short: 20s is enough for the small fixtures above,
    # and prevents a hung CI job when a distant host is slow.
    adapter.fetcher.config = adapter.fetcher.config  # keep politeness as declared
    law = adapter.fetch(law_id)
    assert law.source == source_id
    assert law.law_id
    assert law.title
