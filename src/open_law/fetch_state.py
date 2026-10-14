"""Per-host politeness state for one fetcher session.

Everything the fetcher remembers about a host — the parsed robots.txt,
the last-fetch stamp that spaces requests, the session request count, and
feed/API discovery findings — lives on one :class:`HostState` per host,
owned by :class:`SessionState`. It used to live in four module-level
dictionaries, which meant two fetchers in one process (a second adapter,
a test, a worker thread) shared and corrupted each other's session.

State is keyed by host (``netloc``): robots.txt is read once per host and
reused, discovery findings are reused for ``cache_ttl_seconds``, and every
request — page, probe, or robots.txt itself — is counted against that
host's budget. Mutating accessors take the session lock, so a fetcher
shared between threads still counts and spaces requests per host.
"""

from __future__ import annotations

import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from dataclasses import field

__all__ = ["HostState", "SessionState"]


@dataclass
class HostState:
    """What the fetcher remembers about one host for one session."""

    netloc: str
    robots: urllib.robotparser.RobotFileParser | None = None
    last_fetch_at: float = 0.0
    request_count: int = 0
    # (feed_url, api_hint, probed_at) for this host's origin, or None when
    # discovery has not run yet. Re-probing 8 feed paths + API hints per
    # page would make politeness itself the load.
    discovery: tuple[str | None, str | None, float] | None = None


@dataclass
class SessionState:
    """The per-host state of one :class:`~open_law.fetcher.PoliteFetcher`."""

    hosts: dict[str, HostState] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def host(self, netloc: str) -> HostState:
        """The state for *netloc*, created on first use."""
        with self._lock:
            return self._host_locked(netloc)

    def count_of(self, netloc: str) -> int:
        """Requests already sent to *netloc* this session."""
        with self._lock:
            state = self.hosts.get(netloc)
            return state.request_count if state is not None else 0

    def count_request(self, netloc: str) -> int:
        """Count one sent (or attempted) request against *netloc*.

        Returns the new total. Counting happens for failed requests too: an
        attempt is load on the host whether or not it succeeded.
        """
        with self._lock:
            state = self._host_locked(netloc)
            state.request_count += 1
            return state.request_count

    def reserve_slot(self, netloc: str, delay_seconds: float) -> float:
        """Reserve *netloc*'s next rate-limit slot; returns seconds to wait.

        The slot is stamped *before* the caller sleeps, under the lock, so
        the one-request-per-``delay_seconds`` promise holds even when two
        threads fetch from the same host at once.
        """
        with self._lock:
            state = self._host_locked(netloc)
            now = time.monotonic()
            wait = delay_seconds - (now - state.last_fetch_at)
            if wait < 0:
                wait = 0.0
            state.last_fetch_at = now + wait
            return wait

    def _host_locked(self, netloc: str) -> HostState:
        """The state for *netloc*; the caller must hold the lock."""
        state = self.hosts.get(netloc)
        if state is None:
            state = HostState(netloc=netloc)
            self.hosts[netloc] = state
        return state
