"""Vocabulary of the polite fetcher: errors, configs, and results.

Pure value objects with no I/O — the fetching policy lives in
:mod:`open_law.fetcher` (orchestration), :mod:`open_law.fetch_cache`
(disk persistence), :mod:`open_law.fetch_robots` (robots.txt),
:mod:`open_law.fetch_discovery` (feed/API discovery), and
:mod:`open_law.fetch_wayback` (archive fallback). Re-exported through
:mod:`open_law.fetcher` so ``from open_law.fetcher import FetchConfig``
keeps working.
"""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Self

__all__ = [
    "CONTACT_PLACEHOLDER",
    "AccessDeniedError",
    "BudgetExceededError",
    "ContactRequiredError",
    "FetchConfig",
    "FetchResult",
    "FetchTextResult",
    "Preflight",
    "RobotDeniedError",
    "access_denied_error",
    "http_parts",
]

CONTACT_PLACEHOLDER = "contact@example.com"


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


class ContactRequiredError(ValueError):
    """Raised before a live request when the contact is still the placeholder.

    The charter requires a reachable contact in the User-Agent so a site
    operator can tell you to slow down. Set ``FETCHER_CONTACT`` (or pass
    ``FetchConfig(contact=...)``) before fetching.
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
    """Tuning knobs for :class:`open_law.fetcher.PoliteFetcher`."""

    project_name: str = "open-law"
    # Empty means "read FETCHER_CONTACT when a fetcher is built" — never at
    # import time, so setting the variable later in the process still works.
    contact: str = ""
    delay_seconds: float = 1.0
    timeout_seconds: float = 10.0
    cache_ttl_seconds: float = 24 * 3600
    cache_dir: Path = Path(".cache/fetcher")
    user_agent: str = ""
    max_requests_per_host: int = 100
    wayback_fallback: bool = False

    def resolved_contact(self) -> str:
        """The explicit contact, else ``FETCHER_CONTACT``, else the placeholder."""
        return self.contact or os.environ.get("FETCHER_CONTACT", "") or CONTACT_PLACEHOLDER

    def resolved_user_agent(self) -> str:
        """Contactable User-Agent identifying this project."""
        if self.user_agent:
            return self.user_agent
        return f"{self.project_name}/0.1 (+mailto:{self.resolved_contact()})"

    def require_contact(self) -> None:
        """Raise :class:`ContactRequiredError` while the User-Agent has no real contact."""
        if CONTACT_PLACEHOLDER in self.resolved_user_agent():
            msg = (
                f"refusing to fetch with the placeholder contact {CONTACT_PLACEHOLDER!r}: "
                "set FETCHER_CONTACT to an address site operators can reach"
            )
            raise ContactRequiredError(msg)


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


def http_parts(url: str) -> urllib.parse.SplitResult:
    """Split *url*, refusing non-http(s) URLs with the shared message."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        msg = f"refusing to fetch non-http(s) URL: {url!r}"
        raise ValueError(msg)
    return parts


def access_denied_error(target: str, status: int) -> AccessDeniedError:
    """The access-denied error for *target* (origin or URL) and *status*."""
    msg = f"access denied by {target!r} (HTTP {status}): use its API or ask permission"
    return AccessDeniedError(msg)
