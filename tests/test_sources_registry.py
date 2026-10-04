"""Registry and default-fetcher wiring tests (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_law.fetcher import FetchConfig, PoliteFetcher
from open_law.sources import ADAPTERS, default_fetcher, open_adapter
from open_law.sources.eu import EurlexAdapter
from open_law.sources.uk import LegislationGovUkAdapter


def test_adapter_ids_are_unique() -> None:
    assert len(set(ADAPTERS)) == len(ADAPTERS)
    assert set(ADAPTERS) == {"uk", "jp", "kr", "la", "bd", "np", "eu", "us", "ca", "jlt"}


def test_open_adapter_builds_every_registered_source() -> None:
    for source_id, adapter_cls in ADAPTERS.items():
        adapter = open_adapter(source_id)
        assert isinstance(adapter, adapter_cls)
        assert adapter.fetcher.config.delay_seconds == adapter_cls.crawl_delay_seconds


def test_default_fetcher_carries_adapter_headers_and_delay() -> None:
    fetcher = default_fetcher(EurlexAdapter)
    assert fetcher.config.delay_seconds == EurlexAdapter.crawl_delay_seconds
    assert fetcher._client.headers["Accept"] == "application/rdf+xml"
    assert "open-law" in fetcher._client.headers["User-Agent"]


def test_open_adapter_injects_custom_fetcher(tmp_path: Path) -> None:
    custom = PoliteFetcher(FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0))
    adapter = open_adapter("uk", custom)
    assert isinstance(adapter, LegislationGovUkAdapter)
    assert adapter.fetcher is custom


def test_open_adapter_unknown_source_lists_known() -> None:
    with pytest.raises(ValueError, match="known sources: bd, ca, eu, jlt, jp, kr, la, np, uk, us"):
        open_adapter("mars")
