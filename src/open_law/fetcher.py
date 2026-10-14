"""Polite HTTP fetcher for open_law (httpx engine).

Every web fetch in this project goes through this module: direct HTTP calls
(``requests.get`` / ``httpx.get`` / ``urllib.request.urlopen`` ...) are banned
project-wide by ruff's ``banned-api`` so politeness cannot be bypassed by
accident. Inside this module every request — page, probe, or discovery —
goes through one send method whose order is fixed: **robots.txt → wait →
send → count**. The fetcher refuses work that is disallowed, blocked, or
excessive:

1. **Permission check** — the target path is checked against the site's
   robots.txt (fetched once per host, before any other request to that
   host); disallowed paths raise :class:`RobotDeniedError`. A ``401``/
   ``403`` on preflight means access is denied — the fetcher raises
   :class:`AccessDeniedError` instead of retrying around the block.
2. **Feed first** — before scraping an HTML page, :func:`preflight` probes
   the site's feed endpoints (``/feed``, ``/rss.xml``, ``/atom.xml``, ...).
   When a feed exists, fetch the feed instead of the page: fewer requests,
   explicit update semantics, no HTML parsing.
3. **API second** — when the site advertises a machine API (``/api``,
   ``api.`` subdomain, ``openapi.json``), use it instead of scraping.
   ``preflight`` reports what it found; the caller picks the API. The
   ``api.`` subdomain is a separate host with its own robots.txt.
4. **Load check** — per-host rate limiting (``delay_seconds``, default
   1.0 s) plus a session request budget (``max_requests_per_host``,
   default 100). Exceeding the budget raises :class:`BudgetExceededError`:
   what is polite at 10 requests is a DDoS at 10 000 — stop and ask before
   scaling up.
5. **Cache** — GET responses are cached under ``.cache/fetcher/`` (keyed
   by URL hash) for ``cache_ttl_seconds`` (default 1 day), so re-runs and
   tests never refetch. A cache hit skips the rate-limit wait.

The ``User-Agent`` always identifies this project plus a contact address
(``FetchConfig.contact``, else the ``FETCHER_CONTACT`` env read when the
fetcher is built). While the contact is still ``CONTACT_PLACEHOLDER`` the
fetcher refuses every live request with :class:`ContactRequiredError`, so
an operator can always reach you. CAPTCHA-solving helpers are
deliberately out of scope: if a site blocks bots, use its API or ask
permission instead of bypassing the protection.

Requires the ``httpx`` runtime dependency (added automatically with this
engine). Tests use ``respx``-style monkeypatched transports — no network.

This module is the orchestration layer: vocabulary lives in
:mod:`open_law.fetch_models`, the disk cache in
:mod:`open_law.fetch_cache`, robots.txt in :mod:`open_law.fetch_robots`,
feed/API discovery in :mod:`open_law.fetch_discovery`, and the archive
fallback in :mod:`open_law.fetch_wayback`. Every name those modules
expose is re-exported here so ``from open_law.fetcher import FetchConfig``
keeps working.
"""

from __future__ import annotations

import time
import urllib.parse
import urllib.robotparser
from typing import Self

import httpx

from open_law.fetch_cache import read_cached_body
from open_law.fetch_cache import write_cached_body
from open_law.fetch_discovery import OriginDiscovery
from open_law.fetch_models import AccessDeniedError
from open_law.fetch_models import BudgetExceededError
from open_law.fetch_models import ContactRequiredError
from open_law.fetch_models import FetchConfig
from open_law.fetch_models import FetchResult
from open_law.fetch_models import FetchTextResult
from open_law.fetch_models import Preflight
from open_law.fetch_models import RobotDeniedError
from open_law.fetch_models import access_denied_error as _access_denied
from open_law.fetch_models import http_parts as _http_parts
from open_law.fetch_robots import load_robots_parser
from open_law.fetch_wayback import wayback_for_error_status
from open_law.fetch_wayback import wayback_on_transport_error

__all__ = [
    "AccessDeniedError",
    "BudgetExceededError",
    "ContactRequiredError",
    "FetchConfig",
    "FetchResult",
    "FetchTextResult",
    "PoliteFetcher",
    "Preflight",
    "RobotDeniedError",
    "fetch_text",
    "preflight",
]

_ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser] = {}
_LAST_FETCH_AT: dict[str, float] = {}
_REQUEST_COUNTS: dict[str, int] = {}
# Origin discovery cache: origin -> (feed_url, api_hint, probed_at).
# Feed/API endpoints barely move, so findings are reused for
# `cache_ttl_seconds` instead of re-probing 8+ feed paths + API hints on
# every call. Without this, politeness probing itself becomes the load:
# one page fetch cost HEAD + robots + 8 feed GETs + API probes.
_DISCOVERY_CACHE: dict[str, tuple[str | None, str | None, float]] = {}


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
        """Judge *url*: robots.txt, access, feed, API, load.

        Checks robots.txt first, then probes the page and the origin's
        feed endpoints and API hints (cheap HEAD/GET requests that go
        through :meth:`_send`, so each one is robots-checked,
        rate-limited and counted toward the host budget), and reports the
        session load. Raises :class:`RobotDeniedError` when robots.txt
        disallows the path, :class:`AccessDeniedError` when the site
        answers 401/403, and :class:`BudgetExceededError` when the host
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
        self._robots_gate(url)
        probe = self._probe_page(url)
        self._deny_if_blocked(probe, origin)
        feed_url, api_hint = self._discover(origin)
        return Preflight(
            url=url,
            feed_url=feed_url,
            api_hint=api_hint,
            allowed=True,
            request_count=count,
            request_budget=config.max_requests_per_host,
        )

    def _probe_page(self, url: str) -> httpx.Response:
        """HEAD *url* (GET on 404/405); transport failures deny access."""
        try:
            probe = self._send("HEAD", url)
            if probe.status_code in (404, 405):
                probe = self._send("GET", url)
        except httpx.HTTPError as exc:
            msg = f"preflight probe failed for {url!r}: {exc}"
            raise AccessDeniedError(msg) from exc
        return probe

    def _deny_if_blocked(self, probe: httpx.Response, origin: str) -> None:
        """Raise when the preflight *probe* shows the site denied access."""
        if probe.status_code in (401, 403):
            raise _access_denied(origin, probe.status_code)

    def _robots_parser(self, url: str) -> urllib.robotparser.RobotFileParser:
        """The robots.txt parser for *url*'s origin.

        The robots.txt fetch is the only request that cannot be checked
        against robots.txt; it still needs a real contact, fits the
        budget, waits for the host's slot, and counts.
        """
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = _ROBOTS_CACHE.get(origin)
        if cached is not None:
            return cached
        host = parts.netloc
        self.config.require_contact()
        self._check_budget(host)
        self._wait_for_slot(host)
        try:
            return load_robots_parser(url, self._client, _ROBOTS_CACHE)
        finally:
            _REQUEST_COUNTS[host] = _REQUEST_COUNTS.get(host, 0) + 1

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

    def _send(self, method: str, url: str) -> httpx.Response:
        """The one door to the network: robots → wait → send → count.

        Every page, probe and discovery request goes through here, so the
        order is fixed: robots.txt for *url*'s own host (``api.`` hosts
        included) is fetched and obeyed first, then the contact and host
        budget are checked, the host's rate-limit slot is awaited, the
        request is sent, and the attempt is counted — even when it fails.
        """
        host = _http_parts(url).netloc
        self._robots_gate(url)
        self.config.require_contact()
        self._check_budget(host)
        self._wait_for_slot(host)
        try:
            return self._client.request(method, url, timeout=self.config.timeout_seconds)
        finally:
            _REQUEST_COUNTS[host] = _REQUEST_COUNTS.get(host, 0) + 1

    def _discover(self, origin: str) -> tuple[str | None, str | None]:
        """Cached (feed_url, api_hint) discovery for *origin*.

        Findings are reused for `cache_ttl_seconds`: feed/API endpoints
        barely move, and re-probing 8 feed paths + API hints per page is
        itself impolite. Every probe goes through :meth:`_send`, so a
        feed path robots.txt disallows is never requested or returned.
        """
        discovery = OriginDiscovery(self.config, _DISCOVERY_CACHE, self._send)
        return discovery.discover(origin)

    def _robots_gate(self, url: str) -> None:
        """Scheme and robots.txt gate without feed/API discovery.

        The known-endpoint path for :meth:`fetch_text`: the caller already
        knows the exact machine URL (an API, a bulk data file), so probing
        the origin for feeds would only add load. :meth:`_send` applies
        the budget, rate limit and access denial rules to the request.
        """
        _http_parts(url)
        parser = self._robots_parser(url)
        if not parser.can_fetch(self.config.resolved_user_agent(), url):
            msg = f"robots.txt disallows fetching {url!r}"
            raise RobotDeniedError(msg)

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
        result = wayback_for_error_status(self._client, url, response, self.config, _REQUEST_COUNTS)
        if result is not None:
            self.last_result = result
        return result

    def _wayback_on_transport_error(self, url: str) -> FetchResult | None:
        """Wayback result after a transport failure; None when not attempted/found."""
        result = wayback_on_transport_error(self._client, url, self.config, _REQUEST_COUNTS)
        if result is not None:
            self.last_result = result
        return result

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
        # Cache before the rate limit: a cached body costs the host nothing,
        # so a fully cached re-run must not sleep per item.
        cached_text = read_cached_body(url, config)
        if cached_text is not None:
            result = FetchResult(text=cached_text, url=url)
            self.last_result = result
            return result
        # Network path: fetch the page, falling back to Wayback on
        # httpx transport failures or 5xx — never on 4xx.
        response: httpx.Response | None = None
        try:
            response = self._send("GET", url)
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
        write_cached_body(url, text, config)
        result = FetchResult(text=text, url=url)
        self.last_result = result
        return result

    def fetch_text(self, url: str, *, discover: bool = True) -> FetchTextResult:
        """GET *url* politely: preflight judgement, cached or rate-limited GET.

        Runs :meth:`preflight` first (robots.txt, access, feed/API
        discovery and budget checks), then serves from the on-disk cache
        when fresh, or waits for the host's slot and fetches. Every
        request counts toward the host budget — including the preflight
        probes.

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
        try:
            response = self._send("GET", url)
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
