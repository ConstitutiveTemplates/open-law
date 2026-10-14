"""The Good-future charter's fetch promises, asserted instead of promised.

CHARTER.md says the rules are enforced by the toolchain and not left to
discipline. These tests are the enforcement for §1 ("Respect the source"):
each one fails if the code stops honouring a sentence of the charter.

- robots.txt is read before any other request to a host, and a refusal
  stops the crawl instead of being worked around;
- at most one request per second per host, probes included;
- robots.txt, HEAD and discovery probes all count against the host budget;
- the defaults carry the charter's numbers (1 s, 100 requests), the disk
  cache is consulted before the rate limit, and a placeholder contact
  refuses the request outright.

Everything runs against a fake httpx transport — no network.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

import httpx
import pytest

from open_law import fetch_state
from open_law import fetcher
from open_law.fetcher import ContactRequiredError, FetchConfig, PoliteFetcher, RobotDeniedError

_ROBOTS_ALLOWED = "User-agent: *\nAllow: /\n"

_Handler = Callable[[httpx.Request], httpx.Response]


class Clock:
    """A virtual clock: only the fetcher's sleeps move it.

    Substituted for the ``time`` module inside :mod:`open_law.fetcher` and
    :mod:`open_law.fetch_state`, so the rate-limit arithmetic runs at real
    speed while the test still sees exact request times, and the
    process-wide clock is left untouched.
    """

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        """The virtual clock's current reading."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the virtual clock instead of blocking."""
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def _contact(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fetcher refuses live requests under the placeholder contact."""
    monkeypatch.setenv("FETCHER_CONTACT", "charter-tests@open-law.invalid")


def _virtual_clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Put the fetcher and the host state on one virtual clock."""
    clock = Clock()
    monkeypatch.setattr(fetcher, "time", clock)
    monkeypatch.setattr(fetch_state, "time", clock)
    return clock


def _site(clock: Clock, events: list[tuple[str, str, float]]) -> _Handler:
    """A fake origin recording (method, url, time) for every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        events.append((request.method, str(request.url), clock.now))
        if request.url.path == "/robots.txt":
            if request.url.host == "api.example.com":
                # The api. subdomain is a host of its own, and it says no.
                return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\nAllow: /\n")
        if request.method == "HEAD":
            return httpx.Response(200, text="")
        return httpx.Response(200, text="<html>hi</html>")

    return handler


def _fetcher(tmp_path: Path, handler: _Handler, delay_seconds: float = 0.0) -> PoliteFetcher:
    """A fetcher over the fake origin, with its own cache directory."""
    config = FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=delay_seconds)
    return PoliteFetcher(config, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_no_request_precedes_the_robots_check(tmp_path: Path) -> None:
    """robots.txt is each host's first request — ``api.`` hosts included."""
    events: list[tuple[str, str, float]] = []
    with _fetcher(tmp_path, _site(Clock(), events)) as fetcher_:
        fetcher_.preflight("https://example.com/items/1")
    first_path: dict[str, str] = {}
    for _, url, _ in events:
        parts = httpx.URL(url)
        first_path.setdefault(parts.host or "", parts.path)
    assert first_path == {"example.com": "/robots.txt", "api.example.com": "/robots.txt"}, first_path


def test_robots_denial_stops_the_crawl(tmp_path: Path) -> None:
    """A disallowed path is refused before its probe goes out."""
    events: list[tuple[str, str, float]] = []
    with (
        _fetcher(tmp_path, _site(Clock(), events)) as fetcher_,
        pytest.raises(RobotDeniedError),
    ):
        fetcher_.fetch_text("https://example.com/private/x", discover=False)
    assert [url for _, url, _ in events] == ["https://example.com/robots.txt"]


def test_requests_per_host_never_exceed_one_per_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every request to a host is spaced by ``delay_seconds`` — probes too."""
    clock = _virtual_clock(monkeypatch)
    events: list[tuple[str, str, float]] = []
    with _fetcher(tmp_path, _site(clock, events), delay_seconds=1.0) as fetcher_:
        fetcher_.fetch_text("https://example.com/a")
        fetcher_.fetch_text("https://example.com/b", discover=False)
    times = [timestamp for _, url, timestamp in events if httpx.URL(url).host == "example.com"]
    assert len(times) >= 3, times
    gaps = [later - earlier for earlier, later in pairwise(times)]
    assert all(gap >= 1.0 for gap in gaps), gaps


def test_robots_head_and_discovery_count_toward_the_budget(tmp_path: Path) -> None:
    """The budget is a host-wide request count, not a page count."""
    events: list[tuple[str, str, float]] = []
    with _fetcher(tmp_path, _site(Clock(), events)) as fetcher_:
        fetcher_.preflight("https://example.com/page")
        counted = fetcher_.state.count_of("example.com")
    assert counted >= 1 + 1 + 8, f"robots + HEAD + feed probes must count, got {counted}"
    assert counted == len([event for event in events if httpx.URL(event[1]).host == "example.com"])


def test_defaults_are_the_charter_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One request per second, a 100-request session budget, cache before wait."""
    config = FetchConfig()
    assert config.delay_seconds == 1.0
    assert config.max_requests_per_host == 100
    assert config.cache_ttl_seconds == 24 * 3600

    clock = _virtual_clock(monkeypatch)
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=_ROBOTS_ALLOWED)
        return httpx.Response(200, text="hi")

    with _fetcher(tmp_path, handler, delay_seconds=1.0) as fetcher_:
        fetcher_.fetch_text("https://example.com/a", discover=False)
        sleeps_before = len(clock.sleeps)
        fetcher_.fetch_text("https://example.com/a", discover=False)
    assert requests.count("/a") == 1, requests  # the second call was cached
    assert clock.sleeps, "an uncached fetch must have waited for its slot"
    assert len(clock.sleeps) == sleeps_before  # …and the cached one did not


def test_placeholder_contact_refuses_the_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No request leaves while the User-Agent carries the placeholder."""
    monkeypatch.delenv("FETCHER_CONTACT", raising=False)
    events: list[tuple[str, str, float]] = []
    with (
        _fetcher(tmp_path, _site(Clock(), events)) as fetcher_,
        pytest.raises(ContactRequiredError, match="FETCHER_CONTACT"),
    ):
        fetcher_.fetch_text("https://example.com/a", discover=False)
    assert events == []
