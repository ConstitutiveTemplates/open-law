"""Shared pytest configuration for the template repo's own test suite.

Historical note for future archaeology: a pytest-xdist hook-env isolation
experiment (per-worker ``PRE_COMMIT_HOME``) was tried here in 2026-09 to
mitigate a pre-commit shared-store flake and reverted — the suite
mass-slowed (46s → 7m44s) with 48 failures. The flake itself is gone for
good: the template no longer ships pre-commit (lint runs ruff directly;
hygiene checks moved to the ``_hygiene.yml`` CI workflow).

The fixtures below power the offline source-adapter tests: a fake origin
serving captured API bodies, an adapter factory wired to it, and the
fixture loader itself. No test talks to the network.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import httpx
import pytest

from open_law import fetcher
from open_law.fetcher import FetchConfig, PoliteFetcher
from open_law.sources.base import SourceAdapter
from tests.helpers import FixtureLoader, Offline, RecordingSite

AdapterT = TypeVar("AdapterT", bound=SourceAdapter)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_ROBOTS_ALLOWED = "User-agent: *\nAllow: /\n"


@pytest.fixture(autouse=True)
def _fresh_fetcher_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the fetcher's module-global caches around every test.

    The robots/discovery/request-count state is module-global by design
    (one process, one polite session); tests must each start from a clean
    session or one test's robots cache leaks into the next.
    """
    monkeypatch.setattr(fetcher, "_ROBOTS_CACHE", {})
    monkeypatch.setattr(fetcher, "_LAST_FETCH_AT", {})
    monkeypatch.setattr(fetcher, "_REQUEST_COUNTS", {})
    monkeypatch.setattr(fetcher, "_DISCOVERY_CACHE", {})


@pytest.fixture
def fixture_text() -> FixtureLoader:
    """Load one captured API response body from ``tests/fixtures/``."""

    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _load


@pytest.fixture
def recording_site() -> RecordingSite:
    """Fake origin serving *responses* by path, recording every request URL.

    ``recording_site(responses, seen)`` (robots permissive) or
    ``recording_site(responses, seen, robots=...)``. Served URLs are
    appended to *seen*, so tests can assert exactly which endpoints —
    and query strings — an adapter touched: politeness is part of the
    contract.
    """

    def _site(
        responses: dict[str, str],
        seen: list[str],
        robots: str = _ROBOTS_ALLOWED,
    ) -> Callable[[httpx.Request], httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            seen.append(str(request.url))
            if path == "/robots.txt":
                return httpx.Response(200, text=robots)
            body = responses.get(path)
            if body is None:
                return httpx.Response(404, text="fixture miss")
            return httpx.Response(200, text=body)

        return handler

    return _site


@pytest.fixture
def offline(tmp_path: Path) -> Offline:
    """Adapter factory wired to a zero-delay, on-disk-cached offline fetcher."""

    def _build(
        adapter_cls: type[AdapterT],
        handler: Callable[[httpx.Request], httpx.Response],
    ) -> AdapterT:
        config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return adapter_cls(PoliteFetcher(config, client=client))

    return _build
