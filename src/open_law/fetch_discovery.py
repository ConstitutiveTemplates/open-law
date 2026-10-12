"""Feed-first / API-second discovery for the polite fetcher.

Before scraping an HTML page, the fetcher probes the origin's feed
endpoints (``/feed``, ``/rss.xml``, ``/atom.xml``, ...) and machine-API
hints (``/api``, ``api.`` subdomain, ``openapi.json``). Findings are
cached per origin for ``FetchConfig.cache_ttl_seconds``: without this,
politeness probing itself becomes the load — one page fetch would cost
HEAD + robots + 8 feed GETs + API probes.
"""

from __future__ import annotations

import time
import urllib.parse
import urllib.robotparser
from collections.abc import Callable
from typing import cast

import httpx

from open_law.fetch_models import FetchConfig

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

# Origin discovery cache: origin -> (feed_url, api_hint, probed_at).
DiscoveryCache = dict[str, tuple[str | None, str | None, float]]


def is_feed_response(response: httpx.Response) -> bool:
    """True when *response* looks like a feed (XML type or rss/feed body)."""
    content_type = cast("str", response.headers.get("content-type", ""))
    body = response.text[:500].lower()
    return "xml" in content_type or "<rss" in body or "<feed" in body


def find_feed_url(origin: str, counted_get: Callable[[str], httpx.Response]) -> str | None:
    """First working feed endpoint on *origin*, or None."""
    for path in FEED_PATHS:
        candidate = f"{origin}{path}"
        try:
            response = counted_get(candidate)
        except httpx.HTTPError:
            continue
        if response.status_code != 200:
            continue
        if is_feed_response(response):
            return candidate
    return None


def _probe_exists(
    url: str,
    counted_head: Callable[[str], httpx.Response],
    counted_get: Callable[[str], httpx.Response],
) -> bool:
    """True when a cheap probe shows *url* exists (2xx)."""
    try:
        response = counted_head(url)
    except httpx.HTTPError:
        return False
    if response.status_code < 400:
        return True
    response = counted_get(url)
    return response.status_code < 400


def find_api_hint(
    origin: str,
    counted_head: Callable[[str], httpx.Response],
    counted_get: Callable[[str], httpx.Response],
) -> str | None:
    """First working machine-API hint on *origin*, or None."""
    parts = urllib.parse.urlsplit(origin)
    api_origin = f"{parts.scheme}://api.{parts.netloc}"
    if _probe_exists(f"{api_origin}/", counted_head, counted_get):
        return f"{api_origin}/"
    for path in API_PATHS:
        candidate = f"{origin}{path}"
        if _probe_exists(candidate, counted_head, counted_get):
            return candidate
    return None


class OriginDiscovery:
    """Per-origin feed/API discovery bound to one fetcher session.

    Holds the TTL config, the shared discovery cache, and the
    budget-counted probes so each lookup is ``discover(origin, parser,
    agent)`` — three arguments, like the ``PoliteFetcher._discover``
    method this replaces.
    """

    def __init__(
        self,
        config: FetchConfig,
        discovery_cache: DiscoveryCache,
        counted_head: Callable[[str], httpx.Response],
        counted_get: Callable[[str], httpx.Response],
    ) -> None:
        self._config = config
        self._cache = discovery_cache
        self._counted_head = counted_head
        self._counted_get = counted_get

    def discover(
        self, origin: str, parser: urllib.robotparser.RobotFileParser, agent: str
    ) -> tuple[str | None, str | None]:
        """Cached (feed_url, api_hint) discovery for *origin*.

        Findings are reused for ``cache_ttl_seconds``: feed/API endpoints
        barely move, and re-probing 8 feed paths + API hints per page is
        itself impolite. A feed path robots.txt disallows is never returned:
        the feed switch must not bypass a denial.
        """
        cached = self._cache.get(origin)
        if cached is not None:
            feed_url, api_hint, probed_at = cached
            if time.time() - probed_at < self._config.cache_ttl_seconds:
                return feed_url, api_hint
        feed_url = find_feed_url(origin, self._counted_get)
        if feed_url is not None and not parser.can_fetch(agent, feed_url):
            feed_url = None
        api_hint = find_api_hint(origin, self._counted_head, self._counted_get)
        self._cache[origin] = (feed_url, api_hint, time.time())
        return feed_url, api_hint
