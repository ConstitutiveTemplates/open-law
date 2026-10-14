"""Feed-first / API-second discovery for the polite fetcher.

Before scraping an HTML page, the fetcher probes the origin's feed
endpoints (``/feed``, ``/rss.xml``, ``/atom.xml``, ...) and machine-API
hints (``/api``, ``api.`` subdomain, ``openapi.json``). Findings are kept
on the host's :class:`~open_law.fetch_state.HostState` for
``FetchConfig.cache_ttl_seconds``: without this, politeness probing itself
becomes the load — one page fetch would cost HEAD + robots + 8 feed GETs
+ API probes.
"""

from __future__ import annotations

import time
import urllib.parse
from collections.abc import Callable
from typing import cast

import httpx

from open_law.fetch_models import FetchConfig
from open_law.fetch_models import RobotDeniedError
from open_law.fetch_state import HostState

__all__ = [
    "API_PATHS",
    "FEED_PATHS",
    "OriginDiscovery",
    "find_api_hint",
    "find_feed_url",
    "is_feed_response",
]

# Feed endpoints probed (in order) before falling back to HTML scraping.
# A 200 with an XML content-type counts as "feed exists".
FEED_PATHS: tuple[str, ...] = (
    "/feed",
    "/feed.xml",
    "/rss.xml",
    "/rss",
    "/atom.xml",
    "/atom",
    "/index.xml",
    "/feed.atom",
)

# Machine-API hints probed before falling back to HTML scraping.
API_PATHS: tuple[str, ...] = ("/api", "/api.json", "/openapi.json")

# The fetcher's one network door: ``send(method, url)`` checks robots.txt,
# waits for the host's rate-limit slot, sends, then counts the request.
Send = Callable[[str, str], httpx.Response]


def is_feed_response(response: httpx.Response) -> bool:
    """True when *response* looks like a feed (XML type or rss/feed body)."""
    content_type = cast("str", response.headers.get("content-type", ""))
    body = response.text[:500].lower()
    return "xml" in content_type or "<rss" in body or "<feed" in body


def find_feed_url(origin: str, send: Send) -> str | None:
    """First working feed endpoint on *origin* that robots.txt allows, or None."""
    for path in FEED_PATHS:
        candidate = f"{origin}{path}"
        try:
            response = send("GET", candidate)
        except (httpx.HTTPError, RobotDeniedError):
            continue
        if response.status_code != 200:
            continue
        if is_feed_response(response):
            return candidate
    return None


def _probe_exists(url: str, send: Send) -> bool:
    """True when a cheap probe shows *url* exists (2xx); robots denial means no."""
    try:
        response = send("HEAD", url)
        if response.status_code >= 400:
            response = send("GET", url)
    except (httpx.HTTPError, RobotDeniedError):
        return False
    return response.status_code < 400


def find_api_hint(origin: str, send: Send) -> str | None:
    """First working machine-API hint on *origin*, or None.

    The ``api.`` subdomain is its own host: *send* checks that host's
    robots.txt and rate limit before probing it.
    """
    parts = urllib.parse.urlsplit(origin)
    api_origin = f"{parts.scheme}://api.{parts.netloc}"
    if _probe_exists(f"{api_origin}/", send):
        return f"{api_origin}/"
    for path in API_PATHS:
        candidate = f"{origin}{path}"
        if _probe_exists(candidate, send):
            return candidate
    return None


class OriginDiscovery:
    """Feed/API discovery bound to one host's session state.

    Holds the TTL config and the fetcher's single send function — which
    applies robots.txt, the rate limit and the host budget to every probe
    — so each lookup is ``discover(origin, host_state)``.
    """

    def __init__(self, config: FetchConfig, send: Send) -> None:
        self._config = config
        self._send = send

    def discover(self, origin: str, host: HostState) -> tuple[str | None, str | None]:
        """Cached (feed_url, api_hint) discovery for *origin*.

        Findings are reused for ``cache_ttl_seconds``: feed/API endpoints
        barely move, and re-probing 8 feed paths + API hints per page is
        itself impolite. A feed path robots.txt disallows is never
        requested, so it is never returned: the feed switch must not
        bypass a denial.
        """
        cached = host.discovery
        if cached is not None:
            feed_url, api_hint, probed_at = cached
            if time.time() - probed_at < self._config.cache_ttl_seconds:
                return feed_url, api_hint
        feed_url = find_feed_url(origin, self._send)
        api_hint = find_api_hint(origin, self._send)
        host.discovery = (feed_url, api_hint, time.time())
        return feed_url, api_hint
