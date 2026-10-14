"""Scraping-layer tests: the polite fetcher must actually run offline.

All tests use a fake httpx transport — no network. They prove the
Good-future preflight: feed-first discovery, API hints, robots.txt, access
denials, per-host budgets, rate limiting, and disk caching.

Each test builds its own :class:`PoliteFetcher`, which owns its own
per-host session state; there is no module-global fetcher state to reset
between tests. The charter-level promises (robots before any request,
one request per second per host) are asserted in ``test_charter.py``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace

from open_law.fetcher import (
    AccessDeniedError,
    BudgetExceededError,
    ContactRequiredError,
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
        count = fetcher_.state.count_of("example.com")
        # HEAD probe + robots.txt + 8 feed probes (all 404) + page GET.
        assert count >= 1 + 1 + 8 + 1, f"probes must count, got {count}"
        # Spend the budget exactly: the next request on this host, in this
        # session, must be refused.
        fetcher_.set_config(replace(config, max_requests_per_host=count))
        with pytest.raises(BudgetExceededError):
            fetcher_.preflight("https://example.com/b")


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


def _recorded(
    site: Callable[[httpx.Request], httpx.Response], events: list[tuple[str, str, str]]
) -> Callable[[httpx.Request], httpx.Response]:
    """Wrap *site*, appending ("send", host, path) for every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        events.append(("send", request.url.host, request.url.path))
        return site(request)

    return handler


def _record_waits(monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, str, str]]) -> None:
    """Record ("wait", host, "") whenever the fetcher waits for a host slot."""
    original = PoliteFetcher._wait_for_slot

    def waiting(self: PoliteFetcher, host: str) -> None:
        events.append(("wait", host, ""))
        original(self, host)

    monkeypatch.setattr(PoliteFetcher, "_wait_for_slot", waiting)


def test_preflight_sends_nothing_before_robots(tmp_path: Path) -> None:
    """robots.txt is each host's first request — the api. host included."""
    events: list[tuple[str, str, str]] = []
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(_recorded(_NO_FEED_API_SITE, events))) as fetcher_:
        judged = fetcher_.preflight("https://example.com/items/1")
    assert judged.api_hint == "https://api.example.com/"
    first_path: dict[str, str] = {}
    for _, host, path in events:
        first_path.setdefault(host, path)
    assert first_path == {"example.com": "/robots.txt", "api.example.com": "/robots.txt"}


def test_preflight_robots_denial_sends_no_probe(tmp_path: Path) -> None:
    """A disallowed path is refused before the HEAD probe goes out."""
    events: list[tuple[str, str, str]] = []
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with (
        PoliteFetcher(config, client=_client(_recorded(_DENY_SITE, events))) as fetcher_,
        pytest.raises(RobotDeniedError),
    ):
        fetcher_.preflight("https://example.com/private/secret")
    assert events == [("send", "example.com", "/robots.txt")]


def test_every_request_waits_for_its_host_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery probes are rate-limited too: each send follows a wait."""
    events: list[tuple[str, str, str]] = []
    _record_waits(monkeypatch, events)
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(_recorded(_NO_FEED_SITE, events))) as fetcher_:
        fetcher_.fetch_text("https://example.com/page")
    sends = [index for index, event in enumerate(events) if event[0] == "send"]
    # robots + HEAD + 8 feed GETs + API probes + page GET.
    assert len(sends) > 1 + 1 + 8 + 1
    for index in sends:
        assert index > 0
        assert events[index - 1] == ("wait", events[index][1], ""), events[index - 1 : index + 1]


def test_robots_disallowed_probes_are_never_sent(tmp_path: Path) -> None:
    """Discovery skips feed paths and api. hosts that robots.txt denies."""
    events: list[tuple[str, str, str]] = []

    def site(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            if request.url.host == "api.example.com":
                return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
            return httpx.Response(200, text="User-agent: *\nDisallow: /feed\nAllow: /\n")
        return _FEED_SITE(request)

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(_recorded(site, events))) as fetcher_:
        judged = fetcher_.preflight("https://example.com/page")
    # "Disallow: /feed" is a prefix rule: /feed and /feed.xml are skipped.
    assert judged.feed_url == "https://example.com/rss.xml"
    assert not [path for _, _, path in events if path.startswith("/feed")]
    assert [path for _, host, path in events if host == "api.example.com"] == ["/robots.txt"]


def test_discovery_probe_transport_errors_are_skipped(tmp_path: Path) -> None:
    """A failing probe (HEAD 4xx, then GET transport error) is not an API."""

    def site(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/api" and request.method == "GET":
            msg = "connection reset"
            raise httpx.ConnectError(msg, request=request)
        return _NO_FEED_SITE(request)

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(site)) as fetcher_:
        judged = fetcher_.preflight("https://example.com/page")
    assert judged.api_hint is None


def test_cache_hit_skips_rate_limit_wait(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fully cached re-run must not sleep per item."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=60)
    with PoliteFetcher(config, client=_client(_NO_FEED_SITE)) as fetcher_:
        fetcher_.fetch_text("https://example.com/a", discover=False)
        after_first = len(sleeps)
        fetcher_.fetch_text("https://example.com/a", discover=False)
        fetcher_.fetch_text("https://example.com/a", discover=False)
    assert after_first == 1
    assert len(sleeps) == after_first


def test_placeholder_contact_refuses_live_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No request leaves while the User-Agent carries contact@example.com."""
    monkeypatch.delenv("FETCHER_CONTACT", raising=False)
    events: list[tuple[str, str, str]] = []
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with (
        PoliteFetcher(config, client=_client(_recorded(_NO_FEED_SITE, events))) as fetcher_,
        pytest.raises(ContactRequiredError, match="FETCHER_CONTACT"),
    ):
        fetcher_.fetch_text("https://example.com/a", discover=False)
    assert events == []


def test_contact_env_is_read_when_the_fetcher_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """FETCHER_CONTACT set after import still reaches the User-Agent."""
    monkeypatch.setenv("FETCHER_CONTACT", "late@open-law.invalid")
    assert "late@open-law.invalid" in FetchConfig().resolved_user_agent()
    assert "explicit@open-law.invalid" in FetchConfig(contact="explicit@open-law.invalid").resolved_user_agent()


def test_default_cache_is_the_platform_user_cache() -> None:
    """The cache lives in the platform user cache, not the working directory."""
    cache_dir = FetchConfig().cache_dir
    assert cache_dir.is_absolute()
    assert "open-law" in cache_dir.parts
    assert not str(cache_dir).startswith(".cache")


def test_cache_key_includes_content_negotiation(tmp_path: Path) -> None:
    """The same URL fetched as RDF and as HTML must not share a cache entry."""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if "rdf" in request.headers.get("accept", ""):
            return httpx.Response(200, text="<rdf/>")
        return httpx.Response(200, text="<html>hi</html>")

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    url = "https://example.com/resource"
    with PoliteFetcher(config, headers={"Accept": "application/rdf+xml"}, client=_client(handler)) as rdf:
        assert rdf.fetch_text(url, discover=False) == "<rdf/>"
    with PoliteFetcher(config, headers={"Accept": "text/html"}, client=_client(handler)) as html:
        assert "hi" in html.fetch_text(url, discover=False)
    # Two negotiations, two bodies: the HTML request did not get the RDF one.
    assert requests.count("/resource") == 2
    # …and repeating the RDF request is served from its own entry.
    with PoliteFetcher(config, headers={"Accept": "application/rdf+xml"}, client=_client(handler)) as again:
        assert again.fetch_text(url, discover=False) == "<rdf/>"
    assert requests.count("/resource") == 2


def test_bytes_fetch_caches_raw_bytes(tmp_path: Path) -> None:
    """Binary bodies are cached verbatim: a PDF survives a cache round trip."""
    payload = b"%PDF-1.4\n\x00\xff\xfe binary \x9c"
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, content=payload, headers={"content-type": "application/pdf"})

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(handler)) as fetcher_:
        first = fetcher_.fetch_bytes("https://example.com/doc.pdf")
        second = fetcher_.fetch_bytes("https://example.com/doc.pdf")
    assert first == payload
    assert second == payload  # byte-identical: no UTF-8 round trip
    assert requests.count("/doc.pdf") == 1  # second call came from the cache


def test_bytes_wayback_uses_the_raw_snapshot_url(tmp_path: Path) -> None:
    """Wayback binaries come from the ``id_`` (unmodified) snapshot URL."""
    payload = b"%PDF-1.4 archived"
    seen: list[str] = []
    wayback = json.dumps(
        {
            "archived_snapshots": {
                "closest": {
                    "available": True,
                    "url": "https://web.archive.org/web/20200101000000/https://example.com/doc.pdf",
                    "timestamp": "20200101000000",
                }
            }
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.host == "archive.org":
            return httpx.Response(200, text=wayback, headers={"content-type": "application/json"})
        if request.url.host == "web.archive.org":
            return httpx.Response(200, content=payload)
        return httpx.Response(500, text="boom")

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0, wayback_fallback=True)
    with PoliteFetcher(config, client=_client(handler)) as fetcher_:
        data = fetcher_.fetch_bytes("https://example.com/doc.pdf")
    assert data == payload
    snapshot_urls = [url for url in seen if "web.archive.org" in url]
    assert snapshot_urls == ["https://web.archive.org/web/20200101000000id_/https://example.com/doc.pdf"], snapshot_urls
    assert fetcher_.last_result is not None
    assert fetcher_.last_result.from_wayback is True
    assert list((tmp_path / "cache").glob("*.bin")), "the archived bytes must be cached"


def test_bytes_fetch_denied_caches_nothing(tmp_path: Path) -> None:
    """A 403 on a binary is denied access, and no body is cached."""
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with (
        PoliteFetcher(config, client=_client(_FORBIDDEN_SITE)) as fetcher_,
        pytest.raises(AccessDeniedError),
    ):
        fetcher_.fetch_bytes("https://example.com/private", discover=False)
    assert list((tmp_path / "cache").glob("*.bin")) == []


def test_bytes_fetch_transport_error_raises_with_wayback_off(tmp_path: Path) -> None:
    """Without ``wayback_fallback`` a dead binary fetch raises, unretried."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        raise httpx.ConnectError("connection reset", request=request)

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with (
        PoliteFetcher(config, client=_client(handler)) as fetcher_,
        pytest.raises(httpx.ConnectError),
    ):
        fetcher_.fetch_bytes("https://example.com/doc.pdf", discover=False)


def test_unusable_cache_directory_still_fetches(tmp_path: Path) -> None:
    """A cache that cannot be written (a read-only checkout) is not fatal."""
    blocked = tmp_path / "cache"
    blocked.write_text("a file where the cache directory should be", encoding="utf-8")
    config = FetchConfig(cache_dir=blocked, delay_seconds=0)
    with PoliteFetcher(config, client=_client(_NO_FEED_SITE)) as fetcher_:
        assert "hi" in fetcher_.fetch_text("https://example.com/a", discover=False)
        assert fetcher_.fetch_bytes("https://example.com/a", discover=False) == b"<html><title>hi</title></html>"


def test_damaged_cache_entries_are_misses(tmp_path: Path) -> None:
    """A damaged cache file means "fetch it again", never a crash."""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, text="hi")

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0)
    with PoliteFetcher(config, client=_client(handler)) as fetcher_:
        assert "hi" in fetcher_.fetch_text("https://example.com/a", discover=False)
        entry = next((tmp_path / "cache").glob("*.json"))
        for damaged in ("not json at all", '["a", "list"]', '{"fetched_at": 1, "text": 42}'):
            entry.write_text(damaged, encoding="utf-8")
            assert "hi" in fetcher_.fetch_text("https://example.com/a", discover=False)
    assert requests.count("/a") == 4  # the first fetch, then one per damaged entry


def test_wayback_text_is_cached_under_the_negotiation_key(tmp_path: Path) -> None:
    """A snapshot body is cached like any other fetch, headers included."""
    payload = "<html>archived</html>"
    requests: list[str] = []
    wayback = json.dumps(
        {
            "archived_snapshots": {
                "closest": {
                    "available": True,
                    "url": "https://web.archive.org/web/20200101000000/https://example.com/page",
                    "timestamp": "20200101000000",
                }
            }
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.host == "archive.org":
            return httpx.Response(200, text=wayback, headers={"content-type": "application/json"})
        if request.url.host == "web.archive.org":
            return httpx.Response(200, text=payload)
        return httpx.Response(500, text="boom")

    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0, wayback_fallback=True)
    with PoliteFetcher(config, headers={"Accept": "text/html"}, client=_client(handler)) as fetcher_:
        first = fetcher_.fetch_text("https://example.com/page", discover=False)
        second = fetcher_.fetch_text("https://example.com/page", discover=False)
    assert "archived" in first
    assert second == first  # served from the cache written for this Accept
    assert sum("web.archive.org" in url for url in requests) == 1


def test_two_fetchers_do_not_share_host_state(tmp_path: Path) -> None:
    """Session state is per instance: no cross-talk between fetchers."""
    robots_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        robots_requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, text="hi")

    first = PoliteFetcher(FetchConfig(cache_dir=tmp_path / "a", delay_seconds=0), client=_client(handler))
    second = PoliteFetcher(FetchConfig(cache_dir=tmp_path / "b", delay_seconds=0), client=_client(handler))
    with first:
        first.fetch_text("https://example.com/a", discover=False)
        assert first.state.count_of("example.com") == 2  # robots.txt + page
        assert second.state.count_of("example.com") == 0
        with second:
            second.fetch_text("https://example.com/a", discover=False)
    # Each fetcher read robots.txt for itself: the parser is instance state.
    assert robots_requests.count("https://example.com/robots.txt") == 2
    assert second.state.count_of("example.com") == 2
