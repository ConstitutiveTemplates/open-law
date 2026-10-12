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
    "FetchResult",
    "FetchTextResult",
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
    wayback_fallback: bool = False

    def resolved_user_agent(self) -> str:
        """Contactable User-Agent identifying this project."""
        if self.user_agent:
            return self.user_agent
        return f"{self.project_name}/0.1 (+mailto:{self.contact})"


@dataclass(frozen=True)
class FetchResult:
    """Result of a polite fetch, with Wayback provenance when used."""

    text: str
    url: str
    from_wayback: bool = False
    wayback_url: str | None = None
    wayback_timestamp: str | None = None


class FetchTextResult(str):
    """A ``str`` that also carries Wayback provenance.

    ``PoliteFetcher.fetch_text`` returns this so callers that treat the
    result as a plain string keep working while CLI and tests can inspect
    ``from_wayback`` / ``wayback_url`` / ``wayback_timestamp``.
    """

    from_wayback: bool
    wayback_url: str | None
    wayback_timestamp: str | None

    def __new__(  # type: ignore[misc]
        cls,
        text: str,
        *,
        from_wayback: bool = False,
        wayback_url: str | None = None,
        wayback_timestamp: str | None = None,
    ) -> Self:
        obj = super().__new__(cls, text)
        obj.from_wayback = from_wayback
        obj.wayback_url = wayback_url
        obj.wayback_timestamp = wayback_timestamp
        return obj


def _http_parts(url: str) -> urllib.parse.SplitResult:
    """Split *url*, refusing non-http(s) URLs with the shared message."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        msg = f"refusing to fetch non-http(s) URL: {url!r}"
        raise ValueError(msg)
    return parts


def _access_denied(target: str, status: int) -> AccessDeniedError:
    """The access-denied error for *target* (origin or URL) and *status*."""
    msg = f"access denied by {target!r} (HTTP {status}): use its API or ask permission"
    return AccessDeniedError(msg)


def _is_feed_response(response: httpx.Response) -> bool:
    """True when *response* looks like a feed (XML type or rss/feed body)."""
    content_type = cast("str", response.headers.get("content-type", ""))
    body = response.text[:500].lower()
    return "xml" in content_type or "<rss" in body or "<feed" in body


def _closest_snapshot(data: object) -> tuple[str | None, str | None]:
    """(snapshot_url, timestamp) in a Wayback availability payload, else Nones."""
    if not isinstance(data, dict):
        return None, None
    payload = cast("dict[str, object]", data)
    archived = payload.get("archived_snapshots")
    if not isinstance(archived, dict):
        return None, None
    closest = cast("dict[str, object]", archived).get("closest")
    if not isinstance(closest, dict):
        return None, None
    closest_d = cast("dict[str, object]", closest)
    if not closest_d.get("available"):
        return None, None
    snap_url = closest_d.get("url")
    timestamp = closest_d.get("timestamp")
    if not isinstance(snap_url, str) or not snap_url:
        return None, None
    ts = timestamp if isinstance(timestamp, str) else None
    return snap_url, ts


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
    # Last fetch provenance, set after each fetch_text/fetch_bytes.
    last_result: FetchResult | None = None

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
        self.last_result = None

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
        parts = _http_parts(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        host = parts.netloc
        self._check_budget(host)
        count = _REQUEST_COUNTS.get(host, 0)
        probe = self._probe_page(url)
        self._deny_if_blocked(probe, origin)
        parser = self._robots_parser_counted(url)
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

    def _probe_page(self, url: str) -> httpx.Response:
        """HEAD *url* (GET on 404/405); transport failures deny access."""
        try:
            probe = self._counted_head(url)
            if probe.status_code in (404, 405):
                probe = self._counted_get(url)
        except httpx.HTTPError as exc:
            msg = f"preflight probe failed for {url!r}: {exc}"
            raise AccessDeniedError(msg) from exc
        return probe

    def _deny_if_blocked(self, probe: httpx.Response, origin: str) -> None:
        """Raise when the preflight *probe* shows the site denied access."""
        if probe.status_code in (401, 403):
            raise _access_denied(origin, probe.status_code)

    def _robots_parser_counted(self, url: str) -> urllib.robotparser.RobotFileParser:
        """The robots.txt parser for *url*'s origin, counting its one fetch."""
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        host = parts.netloc
        had_robots = origin in _ROBOTS_CACHE
        parser = _robots_parser(url, self._client)
        if not had_robots:
            _REQUEST_COUNTS[host] = _REQUEST_COUNTS.get(host, 0) + 1
        return parser

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

    def _counted(self, method: str, url: str) -> httpx.Response:
        """Budget-checked *method* request counting toward the host budget."""
        host = urllib.parse.urlsplit(url).netloc
        self._check_budget(host)
        if method == "HEAD":
            response = self._client.head(url, timeout=self.config.timeout_seconds)
        else:
            response = self._client.get(url, timeout=self.config.timeout_seconds)
        _REQUEST_COUNTS[host] = _REQUEST_COUNTS.get(host, 0) + 1
        return response

    def _counted_head(self, url: str) -> httpx.Response:
        """HEAD probe that counts toward the host session budget."""
        return self._counted("HEAD", url)

    def _counted_get(self, url: str) -> httpx.Response:
        """GET probe that counts toward the host session budget."""
        return self._counted("GET", url)

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
            if _is_feed_response(response):
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
        parts = _http_parts(url)
        self._check_budget(parts.netloc)
        parser = self._robots_parser_counted(url)
        if not parser.can_fetch(self.config.resolved_user_agent(), url):
            msg = f"robots.txt disallows fetching {url!r}"
            raise RobotDeniedError(msg)

    def _query_wayback(self, url: str) -> tuple[str | None, str | None]:
        """Query the Wayback availability API for *url*.

        Returns ``(snapshot_url, timestamp)`` when available, else
        ``(None, None)``. Failures are treated as unavailable.
        """
        api_url = f"https://archive.org/wayback/available?url={urllib.parse.quote(url, safe='')}"
        try:
            resp = self._client.get(api_url, timeout=self.config.timeout_seconds)
        except httpx.HTTPError:
            return None, None
        if resp.status_code != 200:
            return None, None
        try:
            data = cast("object", json.loads(resp.text))
        except (ValueError, json.JSONDecodeError):
            return None, None
        return _closest_snapshot(data)

    def _fetch_via_wayback(self, url: str) -> FetchResult | None:
        """Try the Wayback Machine for *url*; None when unavailable."""
        snap_url, timestamp = self._query_wayback(url)
        if snap_url is None:
            return None
        try:
            resp = self._client.get(snap_url, timeout=self.config.timeout_seconds)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        text = resp.text
        _write_cache(url, text, self.config)
        # Count the snapshot fetch toward the wayback host budget (best-effort).
        try:
            host = urllib.parse.urlsplit(snap_url).netloc
            _REQUEST_COUNTS[host] = _REQUEST_COUNTS.get(host, 0) + 1
        except Exception:
            pass
        return FetchResult(text=text, url=url, from_wayback=True, wayback_url=snap_url, wayback_timestamp=timestamp)

    def _resolve_url(self, url: str, *, discover: bool) -> str:
        """Gate *url* and switch to the discovered feed when told to."""
        if discover:
            judged = self.preflight(url)
            if judged.should_use_feed:
                url = judged.feed_url or url
        else:
            self._robots_gate(url)
        return url

    def _wait_for_slot(self, host: str) -> None:
        """Sleep until *host*'s rate-limit delay has elapsed, then stamp it."""
        now = time.monotonic()
        last = _LAST_FETCH_AT.get(host, 0.0)
        wait = self.config.delay_seconds - (now - last)
        if wait > 0:
            time.sleep(wait)
        _LAST_FETCH_AT[host] = time.monotonic()

    def _wayback_for_error_status(self, url: str, response: httpx.Response) -> FetchResult | None:
        """Wayback result for a 5xx *response*; else raise; None on success."""
        if response.status_code >= 500 and self.config.wayback_fallback:
            wb = self._fetch_via_wayback(url)
            if wb is not None:
                self.last_result = wb
                return wb
        response.raise_for_status()
        return None

    def _wayback_on_transport_error(self, url: str) -> FetchResult | None:
        """Wayback result after a transport failure; None when not attempted/found."""
        if self.config.wayback_fallback:
            wb = self._fetch_via_wayback(url)
            if wb is not None:
                self.last_result = wb
                return wb
        return None

    def fetch_result(self, url: str, *, discover: bool = True) -> FetchResult:
        """GET *url* politely, returning a :class:`FetchResult` with provenance.

        When ``wayback_fallback`` is on, network errors (``httpx.HTTPError``)
        or 5xx responses fall back to the Wayback Machine (``4xx`` never
        does — the charter forbids bypassing access control). The snapshot
        URL and timestamp are carried on the result so the CLI can report
        them.
        """
        config = self.config
        url = self._resolve_url(url, discover=discover)
        host = urllib.parse.urlsplit(url).netloc
        self._wait_for_slot(host)
        cached_text = _read_cache(url, config)
        if cached_text is not None:
            result = FetchResult(text=cached_text, url=url)
            self.last_result = result
            return result
        # Network path: fetch the page, falling back to Wayback on
        # httpx transport failures or 5xx — never on 4xx.
        response: httpx.Response | None = None
        try:
            response = self._counted_get(url)
            if response.status_code in (401, 403):
                raise _access_denied(url, response.status_code)
            wb = self._wayback_for_error_status(url, response)
            if wb is not None:
                return wb
        except (AccessDeniedError, RobotDeniedError, BudgetExceededError):
            raise
        except httpx.HTTPStatusError as exc:
            # 4xx/5xx surfaced by raise_for_status — only 5xx already handled above.
            # Re-raise; Wayback was already attempted for 5xx.
            raise exc from None
        except httpx.HTTPError:
            wb = self._wayback_on_transport_error(url)
            if wb is not None:
                return wb
            raise
        # Success path: 2xx.
        assert response is not None
        text = response.text
        _write_cache(url, text, config)
        result = FetchResult(text=text, url=url)
        self.last_result = result
        return result

    def fetch_text(self, url: str, *, discover: bool = True) -> FetchTextResult:
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

        When ``FetchConfig.wayback_fallback`` is enabled, network failures
        (DNS, timeouts, ``httpx.HTTPError``) and 5xx responses fall back
        to ``https://archive.org/wayback/available?url=`` (4xx never does).
        The return value exposes ``from_wayback`` / ``wayback_url`` /
        ``wayback_timestamp`` and ``last_result`` is also updated.
        """
        result = self.fetch_result(url, discover=discover)
        return FetchTextResult(
            result.text,
            from_wayback=result.from_wayback,
            wayback_url=result.wayback_url,
            wayback_timestamp=result.wayback_timestamp,
        )

    def fetch_bytes(self, url: str, *, discover: bool = False) -> bytes:
        """GET *url* as bytes (for PDFs and other binary documents)."""
        # Reuse the same politeness gate as fetch_text, but return raw bytes.
        # Binary responses are not cached as text; cache the decoded text
        # when the server sent text, otherwise skip the text cache.
        url = self._resolve_url(url, discover=discover)
        host = urllib.parse.urlsplit(url).netloc
        self._wait_for_slot(host)
        try:
            response = self._counted_get(url)
            if response.status_code in (401, 403):
                raise _access_denied(url, response.status_code)
            wb = self._wayback_for_error_status(url, response)
            if wb is not None:
                return wb.text.encode("utf-8")
            data = response.content
            # Update last_result for provenance (text view for CLI).
            self.last_result = FetchResult(text=data.decode("utf-8", errors="replace"), url=url)
            return data
        except (AccessDeniedError, RobotDeniedError, BudgetExceededError):
            raise
        except httpx.HTTPError:
            wb = self._wayback_on_transport_error(url)
            if wb is not None:
                return wb.text.encode("utf-8")
            raise


def preflight(url: str, config: FetchConfig | None = None) -> Preflight:
    """One-shot judgement for *url* (opens and closes its own fetcher)."""
    with PoliteFetcher(config) as fetcher:
        return fetcher.preflight(url)


def fetch_text(url: str, config: FetchConfig | None = None) -> FetchTextResult:
    """One-shot polite GET (opens and closes its own fetcher)."""
    with PoliteFetcher(config) as fetcher:
        return fetcher.fetch_text(url)
