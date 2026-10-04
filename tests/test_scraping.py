"""Scraping-layer tests: the polite fetcher must actually run offline.

All tests use a fake httpx transport — no network. They prove the
Good-future preflight: feed-first discovery, API hints, robots.txt, access
denials, per-host budgets, rate limiting, and disk caching.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from collections.abc import Callable
from dataclasses import dataclass

from open_law import fetcher
from open_law.fetcher import (
    AccessDeniedError,
    BudgetExceededError,
    FetchConfig,
    PoliteFetcher,
    RobotDeniedError,
)


def _client(handler: object) -> httpx.Client:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return httpx.Client(transport=transport)


_FEED_PATHS_TAIL = (
    "/feed",
    "/feed.xml",
    "/rss.xml",
    "/rss",
    "/atom.xml",
    "/atom",
    "/index.xml",
    "/feed.atom",
)


def _is_feed_path(path: str) -> bool:
    """True when *path* is one of the probed feed endpoints."""
    return path in _FEED_PATHS_TAIL


def _is_api_request(request: httpx.Request) -> bool:
    """True when *request* targets a probed machine-API hint."""
    return request.url.path in ("/api", "/api.json", "/openapi.json") or (request.url.host == "api.example.com")


def _feed_response(shape: _SiteShape) -> httpx.Response:
    """RSS when the fake origin has a feed, else 404."""
    if shape.feed:
        return httpx.Response(
            200,
            text="<rss><channel><title>t</title></channel></rss>",
            headers={"content-type": "application/rss+xml"},
        )
    return httpx.Response(404, text="no feed")


def _api_response(request: httpx.Request, shape: _SiteShape) -> httpx.Response:
    """{} when the fake api subdomain exists, else 404."""
    if request.url.host == "api.example.com" and shape.api_host:
        return httpx.Response(200, text="{}")
    return httpx.Response(404, text="no api")


@dataclass(frozen=True)
class _SiteShape:
    """Which branches the fake origin serves (no bare bools: FBT001/FBT002)."""

    robots: str = "User-agent: *\\nAllow: /\\n"
    feed: bool = True
    api_host: bool = False
    forbidden_paths: tuple[str, ...] = ()


def _respond(shape: _SiteShape | None = None) -> Callable[[httpx.Request], httpx.Response]:
    """Build a fake-origin handler with the requested shape (no network)."""
    shape = shape or _SiteShape()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=shape.robots)
        if path in shape.forbidden_paths:
            return httpx.Response(403, text="forbidden")
        if _is_feed_path(path):
            return _feed_response(shape)
        if _is_api_request(request):
            return _api_response(request, shape)
        if request.method == "HEAD":
            return httpx.Response(200, text="")
        return httpx.Response(200, text="<html><title>hi</title></html>")

    return handler


_FEED_SITE = _respond()
_NO_FEED_SITE = _respond(_SiteShape(feed=False))
_NO_FEED_API_SITE = _respond(_SiteShape(feed=False, api_host=True))
_DENY_SITE = _respond(_SiteShape(robots="User-agent: *\nDisallow: /private\nAllow: /\n"))
_FORBIDDEN_SITE = _respond(_SiteShape(forbidden_paths=("/private",)))


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetcher, "_ROBOTS_CACHE", {})
    monkeypatch.setattr(fetcher, "_LAST_FETCH_AT", {})
    monkeypatch.setattr(fetcher, "_REQUEST_COUNTS", {})
    monkeypatch.setattr(fetcher, "_DISCOVERY_CACHE", {})


def test_fetch_text_returns_body(tmp_path: Path) -> None:
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(_NO_FEED_SITE)) as fetcher_:
        assert "hi" in fetcher_.fetch_text("https://example.com/page")


def test_preflight_prefers_feed_over_page(tmp_path: Path) -> None:
    """A site with a feed: preflight says so, and fetch uses it."""
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(_FEED_SITE)) as fetcher_:
        judged = fetcher_.preflight("https://example.com/blog/article-1")
        assert judged.should_use_feed is True
        assert judged.feed_url == "https://example.com/feed"
        body = fetcher_.fetch_text("https://example.com/blog/article-1")
        assert "<rss>" in body


def test_preflight_reports_api_hint(tmp_path: Path) -> None:
    """A site with no feed but an api subdomain: prefer the API."""
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(_NO_FEED_API_SITE)) as fetcher_:
        judged = fetcher_.preflight("https://example.com/items/1")
        assert judged.should_use_feed is False
        assert judged.should_use_api is True
        assert judged.api_hint == "https://api.example.com/"


def test_robots_disallow_raises(tmp_path: Path) -> None:
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with (
        PoliteFetcher(config, client=_client(_DENY_SITE)) as fetcher_,
        pytest.raises(RobotDeniedError),
    ):
        fetcher_.fetch_text("https://example.com/private/secret")


def test_access_denied_raises_without_retry(tmp_path: Path) -> None:
    """401/403 means the site said no: raise, do not work around it."""
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with (
        PoliteFetcher(config, client=_client(_FORBIDDEN_SITE)) as fetcher_,
        pytest.raises(AccessDeniedError),
    ):
        fetcher_.preflight("https://example.com/private")
    with (
        PoliteFetcher(config, client=_client(_FORBIDDEN_SITE)) as fetcher_,
        pytest.raises(AccessDeniedError),
    ):
        fetcher_.fetch_text("https://example.com/private")


def test_budget_exceeded_stops_the_crawl(tmp_path: Path) -> None:
    """Exceeding max_requests_per_host stops with BudgetExceededError.

    Probes count too: a budget of 1 is already spent by the first
    preflight's own HEAD probe, so even the first judgement fails loudly
    instead of silently under-counting.
    """
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0, max_requests_per_host=1)
    with (
        PoliteFetcher(config, client=_client(_FEED_SITE)) as fetcher_,
        pytest.raises(BudgetExceededError),
    ):
        fetcher_.preflight("https://example.com/a")


def test_budget_counts_probes_and_pages(tmp_path: Path) -> None:
    """Probes count toward the budget: one page costs HEAD + robots + feed."""
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(_NO_FEED_SITE)) as fetcher_:
        fetcher_.fetch_text("https://example.com/a")
        count = fetcher._REQUEST_COUNTS.get("example.com", 0)
        # HEAD probe + robots.txt + 8 feed probes (all 404) + page GET.
        assert count >= 1 + 1 + 8 + 1, f"probes must count, got {count}"
        with pytest.raises(BudgetExceededError):
            PoliteFetcher(
                FetchConfig(
                    cache_dir=tmp_path / "cache",
                    delay_seconds=0,
                    max_requests_per_host=count,
                ),
                client=_client(_NO_FEED_SITE),
            ).preflight("https://example.com/b")


def test_rate_limit_sleeps_between_hosts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=60)
    with PoliteFetcher(config, client=_client(_NO_FEED_SITE)) as fetcher_:
        fetcher_.fetch_text("https://example.com/a")
        fetcher_.fetch_text("https://example.com/b")
    assert sleeps and sleeps[0] > 0


def test_disk_cache_avoids_second_fetch(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        return _NO_FEED_SITE(request)

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(handler)) as fetcher_:
        first = fetcher_.fetch_text("https://example.com/page")
        second = fetcher_.fetch_text("https://example.com/page")
    assert first == second
    # Preflight probes (HEAD + feed/API discovery) run on both calls; only
    # the page body GET itself must happen once — the rerun serves cache.
    page_gets = [url for method, url in calls if method == "GET" and url == "https://example.com/page"]
    assert len(page_gets) == 1


def test_discovery_cached_per_origin(tmp_path: Path) -> None:
    """Second page on the same origin reuses discovery: no feed re-probing."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _FEED_SITE(request)

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(handler)) as fetcher_:
        fetcher_.preflight("https://example.com/blog/a")
        feed_probes_first = [url for url in calls if "/feed" in url or "/rss" in url or "/atom" in url]
        assert feed_probes_first, "first preflight must probe feed endpoints"
        calls.clear()
        judged = fetcher_.preflight("https://example.com/blog/b")
        assert judged.should_use_feed is True
        feed_probes_second = [url for url in calls if "/feed" in url or "/rss" in url or "/atom" in url]
        assert feed_probes_second == [], f"second preflight must not re-probe feeds: {feed_probes_second}"


def test_fetch_without_discovery_keeps_exact_url(tmp_path: Path) -> None:
    """discover=False serves the known endpoint as-is: no feed switch."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _FEED_SITE(request)

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(handler)) as fetcher_:
        body = fetcher_.fetch_text("https://example.com/api/data", discover=False)
    assert "hi" in body
    assert "<rss>" not in body
    assert not any("/feed" in url for url in calls), f"known-endpoint fetch must not probe feeds: {calls}"


def test_fetch_without_discovery_still_gates_on_robots(tmp_path: Path) -> None:
    """The known-endpoint path keeps every robots.txt promise."""
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with (
        PoliteFetcher(config, client=_client(_DENY_SITE)) as fetcher_,
        pytest.raises(RobotDeniedError),
    ):
        fetcher_.fetch_text("https://example.com/private/x", discover=False)


def test_fetch_without_discovery_counts_budget(tmp_path: Path) -> None:
    """robots.txt + GET both count: a budget of 1 cannot fetch at all."""
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0, max_requests_per_host=1)
    with (
        PoliteFetcher(config, client=_client(_NO_FEED_SITE)) as fetcher_,
        pytest.raises(BudgetExceededError),
    ):
        fetcher_.fetch_text("https://example.com/a", discover=False)


def test_extra_headers_reach_the_transport(tmp_path: Path) -> None:
    """headers= merges with the contactable User-Agent on the same client."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, text="ok")

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(
        config,
        headers={"Accept": "application/rdf+xml"},
        transport=httpx.MockTransport(handler),
    ) as fetcher_:
        fetcher_.fetch_text("https://example.com/resource", discover=False)
    assert seen["accept"] == "application/rdf+xml"
    assert "open-law" in seen["user-agent"]
