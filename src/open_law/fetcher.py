"""Polite HTTP fetcher for open_law (httpx engine).

Every web fetch in this project goes through this module: direct HTTP calls
(``requests.get`` / ``httpx.get`` / ``urllib.request.urlopen`` ...) are banned
project-wide by ruff's ``banned-api`` so politeness cannot be bypassed by
accident. The fetcher enforces the Good-future preflight on every call —
**feed first, API second, scraping last** — and refuses work that is
disallowed, blocked, or excessive:

1. **Feed first** — before scraping an HTML page, :func:`preflight` probes
   the site's feed endpoints (``/feed``, ``/rss.xml``, ``/atom.xml``, ...).
   When a feed exists, fetch the feed instead of the page: fewer requests,
   explicit update semantics, no HTML parsing.
2. **API second** — when the site advertises a machine API (``/api``,
   ``api.`` subdomain, ``openapi.json``), use it instead of scraping.
   ``preflight`` reports what it found; the caller picks the API.
3. **Permission check** — the target path is checked against the site's
   robots.txt (cached per host); disallowed paths raise
   :class:`RobotDeniedError`. A ``401``/``403`` on preflight means access
   is denied — the fetcher raises :class:`AccessDeniedError` instead of
   retrying around the block.
4. **Load check** — per-host rate limiting (``delay_seconds``, default
   1.0 s) plus a session request budget (``max_requests_per_host``,
   default 100). Exceeding the budget raises :class:`BudgetExceededError`:
   what is polite at 10 requests is a DDoS at 10 000 — stop and ask before
   scaling up.
5. **Cache** — GET responses are cached under ``.cache/fetcher/`` (keyed
   by URL hash) for ``cache_ttl_seconds`` (default 1 day), so re-runs and
   tests never refetch.

The ``User-Agent`` always identifies this project plus a contact address
(``FETCHER_CONTACT`` env or the placeholder below — replace it before any
real crawl so the operator can reach you). CAPTCHA-solving helpers are
deliberately out of scope: if a site blocks bots, use its API or ask
permission instead of bypassing the protection.

Requires the ``httpx`` runtime dependency (added automatically with this
engine). Tests use ``respx``-style monkeypatched transports — no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from typing import cast

import httpx

__all__ = [
    "AccessDeniedError",
    "BudgetExceededError",
    "FetchConfig",
    "PoliteFetcher",
    "Preflight",
    "RobotDeniedError",
    "fetch_text",
    "preflight",
]

CONTACT_PLACEHOLDER = "contact@example.com"

_ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser] = {}
_LAST_FETCH_AT: dict[str, float] = {}
_REQUEST_COUNTS: dict[str, int] = {}
# Origin discovery cache: origin -> (feed_url, api_hint, probed_at).
# Feed/API endpoints barely move, so findings are reused for
# `cache_ttl_seconds` instead of re-probing 8+ feed paths + API hints on
# every call. Without this, politeness probing itself becomes the load:
# one page fetch cost HEAD + robots + 8 feed GETs + API probes.
_DISCOVERY_CACHE: dict[str, tuple[str | None, str | None, float]] = {}

# Feed endpoints probed (in order) before falling back to HTML scraping.
# A 200 with an XML content-type counts as "feed exists".
_FEED_PATHS: tuple[str, ...] = (
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
_API_PATHS: tuple[str, ...] = ("/api", "/api.json", "/openapi.json")


class RobotDeniedError(ValueError):
    """Raised when the site's robots.txt disallows the requested path."""


class AccessDeniedError(ValueError):
    """Raised when the site denies access (401/403 on preflight).

    Do not retry around the block, rotate user-agents, or reach for a
    CAPTCHA solver — the site said no. Use its API or ask permission.
    """


class BudgetExceededError(ValueError):
    """Raised when the per-host session budget is exhausted.

    What is polite at 10 requests is a DDoS at 10 000. Stop, file an issue
    describing the crawl size, and get review before raising
    ``max_requests_per_host``.
    """


@dataclass(frozen=True)
class Preflight:
    """The fetcher's judgement about *url*, before any page is fetched.

    - ``feed_url``: a working feed endpoint found on the same host, or
      ``None``. When set, fetch the feed — not the HTML page.
    - ``api_hint``: a discovered machine-API hint (``/api``, ``api.``
      subdomain, ``openapi.json``), or ``None``. When set, prefer the API
      over scraping.
    - ``allowed``: robots.txt permits the path.
    - ``request_count`` / ``request_budget``: session usage on this host.
    """

    url: str
    feed_url: str | None
    api_hint: str | None
    allowed: bool
    request_count: int
    request_budget: int

    @property
    def should_use_feed(self) -> bool:
        """True when a feed exists: fetch it instead of the HTML page."""
        return self.feed_url is not None

    @property
    def should_use_api(self) -> bool:
        """True when a machine API was found: prefer it over scraping."""
        return self.feed_url is None and self.api_hint is not None

    @property
    def excessive(self) -> bool:
        """True when the host budget is exhausted: stop, do not scale up."""
        return self.request_count >= self.request_budget


@dataclass(frozen=True)
class FetchConfig:
    """Tuning knobs for :class:`PoliteFetcher`."""

    project_name: str = "open-law"
    contact: str = os.environ.get("FETCHER_CONTACT", CONTACT_PLACEHOLDER)
    delay_seconds: float = 1.0
    timeout_seconds: float = 10.0
    cache_ttl_seconds: float = 24 * 3600
    cache_dir: Path = Path(".cache/fetcher")
    user_agent: str = ""
    max_requests_per_host: int = 100

    def resolved_user_agent(self) -> str:
        """Contactable User-Agent identifying this project."""
        if self.user_agent:
            return self.user_agent
        return f"{self.project_name}/0.1 (+mailto:{self.contact})"


def _robots_parser(base_url: str, client: httpx.Client) -> urllib.robotparser.RobotFileParser:
    """Fetch (once per host) and parse the site's robots.txt."""
    parts = urllib.parse.urlsplit(base_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    cached = _ROBOTS_CACHE.get(origin)
    if cached is not None:
        return cached
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(f"{origin}/robots.txt")
    try:
        response = client.get(f"{origin}/robots.txt", timeout=10.0)
        lines = response.text.splitlines() if response.status_code == 200 else []
    except httpx.HTTPError:
        lines = []
    parser.parse(lines)
    _ROBOTS_CACHE[origin] = parser
    return parser


def _cache_path(url: str, cache_dir: Path) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return cache_dir / f"{digest}.json"


def _write_cache(url: str, text: str, config: FetchConfig) -> None:
    """Persist a GET body for *url*; best-effort (disk errors are ignored)."""
    try:
        config.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = _cache_path(url, config.cache_dir)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"url": url, "fetched_at": time.time(), "text": text}),
            encoding="utf-8",
        )
        tmp.replace(cache_file)
    except OSError:
        pass


def _read_cache(url: str, config: FetchConfig) -> str | None:
    """Fresh cached body for *url*, or None on miss/expiry/corruption."""
    cache_file = _cache_path(url, config.cache_dir)
    if not cache_file.exists():
        return None
    try:
        decoded = cast("object", json.loads(cache_file.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
    if not isinstance(decoded, dict):
        return None
    payload = cast("dict[str, object]", decoded)
    fetched_at = payload.get("fetched_at", 0.0)
    stamp = fetched_at if isinstance(fetched_at, (int, float)) else 0.0
    if time.time() - stamp >= config.cache_ttl_seconds:
        return None
    cached = payload.get("text", "")
    return cached if isinstance(cached, str) else None


class PoliteFetcher:
    """httpx-backed polite fetcher: robots check + rate limit + disk cache."""

    config: FetchConfig
    _client: httpx.Client
    _owns_client: bool

    def __init__(
        self,
        config: FetchConfig | None = None,
        client: httpx.Client | None = None,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or FetchConfig()
        if client is None:
            merged = {"User-Agent": self.config.resolved_user_agent()}
            merged.update(headers or {})
            self._client = httpx.Client(
                headers=merged,
                follow_redirects=True,
                timeout=self.config.timeout_seconds,
                transport=transport,
            )
            self._owns_client = True
        else:
            self._client = client
            self._owns_client = False

    def close(self) -> None:
        """Close the owned httpx client (no-op for injected clients)."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def preflight(self, url: str) -> Preflight:
        """Judge *url* before fetching: feed, API, permission, load.

        Probes feed endpoints and API hints on the same host (cheap HEAD/GET
        requests that count toward the host budget), checks robots.txt, and
        reports the session load. Raises :class:`AccessDeniedError` when the
        site answers 401/403, :class:`RobotDeniedError` when robots.txt
        disallows the path, and :class:`BudgetExceededError` when the host
        budget is exhausted. Discovery findings are cached per origin, so
        repeat pages cost one HEAD probe instead of 8+ feed GETs. Callers
        inspect ``should_use_feed`` / ``should_use_api`` / ``excessive`` to
        decide what to fetch.
        """
        config = self.config
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            msg = f"refusing to fetch non-http(s) URL: {url!r}"
            raise ValueError(msg)
        origin = f"{parts.scheme}://{parts.netloc}"
        host = parts.netloc
        self._check_budget(host)
        count = _REQUEST_COUNTS.get(host, 0)
        try:
            probe = self._counted_head(url)
            if probe.status_code in (404, 405):
                probe = self._counted_get(url)
        except httpx.HTTPError as exc:
            msg = f"preflight probe failed for {url!r}: {exc}"
            raise AccessDeniedError(msg) from exc
        if probe.status_code in (401, 403):
            msg = f"access denied by {origin!r} (HTTP {probe.status_code}): use its API or ask permission"
            raise AccessDeniedError(msg)
        had_robots = origin in _ROBOTS_CACHE
        parser = _robots_parser(url, self._client)
        if not had_robots:
            _REQUEST_COUNTS[host] = _REQUEST_COUNTS.get(host, 0) + 1
        allowed = parser.can_fetch(config.resolved_user_agent(), url)
        if not allowed:
            msg = f"robots.txt disallows fetching {url!r}"
            raise RobotDeniedError(msg)
        agent = config.resolved_user_agent()
        feed_url, api_hint = self._discover(origin, parser, agent)
        return Preflight(
            url=url,
            feed_url=feed_url,
            api_hint=api_hint,
            allowed=allowed,
            request_count=count,
            request_budget=config.max_requests_per_host,
        )

    def _check_budget(self, host: str) -> None:
        """Raise BudgetExceededError when *host* exhausted its session budget."""
        count = _REQUEST_COUNTS.get(host, 0)
        if count >= self.config.max_requests_per_host:
            msg = (
                f"host budget exhausted for {host!r}: {count} requests "
                f"(max {self.config.max_requests_per_host}). Stop — what is polite "
                "at 10 requests is a DDoS at 10 000."
            )
            raise BudgetExceededError(msg)

    def _counted_head(self, url: str) -> httpx.Response:
        """HEAD probe that counts toward the host session budget."""
        host = urllib.parse.urlsplit(url).netloc
        self._check_budget(host)
        response = self._client.head(url, timeout=self.config.timeout_seconds)
        _REQUEST_COUNTS[host] = _REQUEST_COUNTS.get(host, 0) + 1
        return response

    def _counted_get(self, url: str) -> httpx.Response:
        """GET probe that counts toward the host session budget."""
        host = urllib.parse.urlsplit(url).netloc
        self._check_budget(host)
        response = self._client.get(url, timeout=self.config.timeout_seconds)
        _REQUEST_COUNTS[host] = _REQUEST_COUNTS.get(host, 0) + 1
        return response

    def _discover(
        self, origin: str, parser: urllib.robotparser.RobotFileParser, agent: str
    ) -> tuple[str | None, str | None]:
        """Cached (feed_url, api_hint) discovery for *origin*.

        Findings are reused for `cache_ttl_seconds`: feed/API endpoints
        barely move, and re-probing 8 feed paths + API hints per page is
        itself impolite. Counts the discovery probes toward the budget on
        a cache miss. A feed path robots.txt disallows is never returned:
        the feed switch must not bypass a denial.
        """
        cached = _DISCOVERY_CACHE.get(origin)
        if cached is not None:
            feed_url, api_hint, probed_at = cached
            if time.time() - probed_at < self.config.cache_ttl_seconds:
                return feed_url, api_hint
        feed_url = self._find_feed(origin)
        if feed_url is not None and not parser.can_fetch(agent, feed_url):
            feed_url = None
        api_hint = self._find_api(origin)
        _DISCOVERY_CACHE[origin] = (feed_url, api_hint, time.time())
        return feed_url, api_hint

    def _head_ok(self, url: str) -> bool:
        """True when a cheap probe shows *url* exists (2xx)."""
        try:
            response = self._counted_head(url)
        except httpx.HTTPError:
            return False
        if response.status_code < 400:
            return True
        response = self._counted_get(url)
        return response.status_code < 400

    def _find_feed(self, origin: str) -> str | None:
        """First working feed endpoint on *origin*, or None."""
        for path in _FEED_PATHS:
            candidate = f"{origin}{path}"
            try:
                response = self._counted_get(candidate)
            except httpx.HTTPError:
                continue
            if response.status_code != 200:
                continue
            content_type = cast("str", response.headers.get("content-type", ""))
            body = response.text[:500].lower()
            if "xml" in content_type or "<rss" in body or "<feed" in body:
                return candidate
        return None

    def _find_api(self, origin: str) -> str | None:
        """First working machine-API hint on *origin*, or None."""
        parts = urllib.parse.urlsplit(origin)
        api_origin = f"{parts.scheme}://api.{parts.netloc}"
        if self._head_ok(f"{api_origin}/"):
            return f"{api_origin}/"
        for path in _API_PATHS:
            candidate = f"{origin}{path}"
            if self._head_ok(candidate):
                return candidate
        return None

    def _robots_gate(self, url: str) -> None:
        """Scheme, budget and robots.txt gate without feed/API discovery.

        The known-endpoint path for :meth:`fetch_text`: the caller already
        knows the exact machine URL (an API, a bulk data file), so probing
        the origin for feeds would only add load — robots.txt, budget,
        and the access denial rules still apply in full.
        """
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            msg = f"refusing to fetch non-http(s) URL: {url!r}"
            raise ValueError(msg)
        host = parts.netloc
        self._check_budget(host)
        origin = f"{parts.scheme}://{parts.netloc}"
        had_robots = origin in _ROBOTS_CACHE
        parser = _robots_parser(url, self._client)
        if not had_robots:
            _REQUEST_COUNTS[host] = _REQUEST_COUNTS.get(host, 0) + 1
        if not parser.can_fetch(self.config.resolved_user_agent(), url):
            msg = f"robots.txt disallows fetching {url!r}"
            raise RobotDeniedError(msg)

    def fetch_text(self, url: str, *, discover: bool = True) -> str:
        """GET *url* politely: preflight judgement, rate limit, cached GET.

        Runs :meth:`preflight` first (feed/API discovery, robots.txt,
        access and budget checks), then rate-limits and serves from the
        on-disk cache when fresh. Every request counts toward the host
        budget — including the preflight probes.

        ``discover=False`` skips feed/API discovery and the feed switch
        for callers that already hold a known machine endpoint (API or
        bulk data URL): robots.txt, budget, rate limiting and caching
        still apply. Use it for adapter-style fetches so the discovery
        probes — and a feed switch that would swap the API URL for a
        feed — cannot get in the way.
        """
        config = self.config
        if discover:
            judged = self.preflight(url)
            if judged.should_use_feed:
                # Safe: preflight denied the requested path already, and
                # _discover drops robots-disallowed feed paths — feed_url is
                # always fetchable when returned.
                url = judged.feed_url or url
        else:
            self._robots_gate(url)
        parts = urllib.parse.urlsplit(url)
        host = parts.netloc
        now = time.monotonic()
        last = _LAST_FETCH_AT.get(host, 0.0)
        wait = config.delay_seconds - (now - last)
        if wait > 0:
            time.sleep(wait)
        _LAST_FETCH_AT[host] = time.monotonic()
        cached_text = _read_cache(url, config)
        if cached_text is not None:
            return cached_text
        self._check_budget(host)
        response = self._client.get(url, timeout=config.timeout_seconds)
        _REQUEST_COUNTS[host] = _REQUEST_COUNTS.get(host, 0) + 1
        if response.status_code in (401, 403):
            msg = f"access denied by {url!r} (HTTP {response.status_code}): use its API or ask permission"
            raise AccessDeniedError(msg)
        response.raise_for_status()
        text = response.text
        _write_cache(url, text, config)
        return text


def preflight(url: str, config: FetchConfig | None = None) -> Preflight:
    """One-shot judgement for *url* (opens and closes its own fetcher)."""
    with PoliteFetcher(config) as fetcher:
        return fetcher.preflight(url)


def fetch_text(url: str, config: FetchConfig | None = None) -> str:
    """One-shot polite GET (opens and closes its own fetcher)."""
    with PoliteFetcher(config) as fetcher:
        return fetcher.fetch_text(url)
