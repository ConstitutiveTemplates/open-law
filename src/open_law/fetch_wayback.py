"""Wayback Machine fallback for the polite fetcher.

When ``FetchConfig.wayback_fallback`` is on, network errors
(``httpx.HTTPError``) or 5xx responses fall back to the Wayback
availability API (4xx never does — the charter forbids bypassing
access control). Both paths fetch the snapshot through its **raw**
(``id_``) URL, which returns the archived payload byte-for-byte instead
of a rewritten page, and carry snapshot URL/timestamp provenance on
:class:`open_law.fetch_models.FetchResult` (text) or
:class:`open_law.fetch_models.FetchBytesResult` (binary) so the CLI can
report it.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import cast

import httpx

from open_law.fetch_models import FetchBytesResult
from open_law.fetch_models import FetchConfig
from open_law.fetch_models import FetchResult
from open_law.fetch_state import SessionState

__all__ = [
    "closest_snapshot",
    "fetch_bytes_via_wayback",
    "fetch_via_wayback",
    "query_wayback",
    "raw_snapshot_url",
    "wayback_bytes_for_error_status",
    "wayback_bytes_on_transport_error",
    "wayback_for_error_status",
    "wayback_on_transport_error",
]

# https://web.archive.org/web/<timestamp>/<original-url> — the ``id_``
# marker goes immediately after the timestamp.
_RAW_SNAPSHOT_RE = re.compile(r"^(https?://web\.archive\.org/web/\d+)(/.*)$")


def raw_snapshot_url(snapshot_url: str) -> str:
    """The ``id_`` (unmodified) form of a Wayback snapshot URL.

    Wayback rewrites HTML and re-encodes payloads on the way out. Asking
    for ``<timestamp>id_`` returns the archived bytes exactly as captured,
    which is what a PDF — or a document the fetcher is about to hash —
    needs. URLs that do not look like snapshots are returned unchanged.
    """
    match = _RAW_SNAPSHOT_RE.match(snapshot_url)
    if match is None:
        return snapshot_url
    return f"{match.group(1)}id_{match.group(2)}"


def closest_snapshot(data: object) -> tuple[str | None, str | None]:
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


def query_wayback(client: httpx.Client, url: str, config: FetchConfig) -> tuple[str | None, str | None]:
    """Query the Wayback availability API for *url*.

    Returns ``(snapshot_url, timestamp)`` when available, else
    ``(None, None)``. Failures are treated as unavailable.
    """
    api_url = f"https://archive.org/wayback/available?url={urllib.parse.quote(url, safe='')}"
    try:
        resp = client.get(api_url, timeout=config.timeout_seconds)
    except httpx.HTTPError:
        return None, None
    if resp.status_code != 200:
        return None, None
    try:
        data = cast("object", json.loads(resp.text))
    except (ValueError, json.JSONDecodeError):
        return None, None
    return closest_snapshot(data)


def _snapshot_bytes(client: httpx.Client, snap_url: str, config: FetchConfig) -> bytes | None:
    """The archived payload at *snap_url*, raw (``id_``), or None."""
    try:
        resp = client.get(raw_snapshot_url(snap_url), timeout=config.timeout_seconds)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    return resp.content


def _snapshot(
    client: httpx.Client,
    url: str,
    config: FetchConfig,
    state: SessionState,
) -> tuple[bytes, str, str | None] | None:
    """(payload, snapshot_url, timestamp) for *url*, or None when unavailable."""
    snap_url, timestamp = query_wayback(client, url, config)
    if snap_url is None:
        return None
    data = _snapshot_bytes(client, snap_url, config)
    if data is None:
        return None
    state.count_request(urllib.parse.urlsplit(snap_url).netloc)
    return data, snap_url, timestamp


def fetch_via_wayback(
    client: httpx.Client,
    url: str,
    config: FetchConfig,
    state: SessionState,
) -> FetchResult | None:
    """Try the Wayback Machine for *url* as text; None when unavailable.

    The raw snapshot payload is decoded for text callers (the bytes path is
    :func:`fetch_bytes_via_wayback`). Caching is the fetcher's job: only it
    knows the content-negotiation headers the cache key carries.
    """
    snapshot = _snapshot(client, url, config, state)
    if snapshot is None:
        return None
    data, snap_url, timestamp = snapshot
    text = data.decode("utf-8", errors="replace")
    return FetchResult(text=text, url=url, from_wayback=True, wayback_url=snap_url, wayback_timestamp=timestamp)


def fetch_bytes_via_wayback(
    client: httpx.Client,
    url: str,
    config: FetchConfig,
    state: SessionState,
) -> FetchBytesResult | None:
    """Try the Wayback Machine for *url* as bytes; None when unavailable.

    The payload is the archived file itself (raw ``id_`` snapshot), so a
    PDF or other non-UTF-8 document survives the round trip intact.
    """
    snapshot = _snapshot(client, url, config, state)
    if snapshot is None:
        return None
    data, snap_url, timestamp = snapshot
    return FetchBytesResult(
        data=data,
        url=url,
        from_wayback=True,
        wayback_url=snap_url,
        wayback_timestamp=timestamp,
    )


def wayback_for_error_status(
    client: httpx.Client,
    url: str,
    response: httpx.Response,
    config: FetchConfig,
    state: SessionState,
) -> FetchResult | None:
    """Wayback text result for a 5xx *response*; else raise; None on success."""
    if response.status_code >= 500 and config.wayback_fallback:
        wb = fetch_via_wayback(client, url, config, state)
        if wb is not None:
            return wb
    response.raise_for_status()
    return None


def wayback_on_transport_error(
    client: httpx.Client,
    url: str,
    config: FetchConfig,
    state: SessionState,
) -> FetchResult | None:
    """Wayback text result after a transport failure; None when not attempted/found."""
    if config.wayback_fallback:
        return fetch_via_wayback(client, url, config, state)
    return None


def wayback_bytes_for_error_status(
    client: httpx.Client,
    url: str,
    response: httpx.Response,
    config: FetchConfig,
    state: SessionState,
) -> FetchBytesResult | None:
    """Wayback bytes result for a 5xx *response*; else raise; None on success."""
    if response.status_code >= 500 and config.wayback_fallback:
        wb = fetch_bytes_via_wayback(client, url, config, state)
        if wb is not None:
            return wb
    response.raise_for_status()
    return None


def wayback_bytes_on_transport_error(
    client: httpx.Client,
    url: str,
    config: FetchConfig,
    state: SessionState,
) -> FetchBytesResult | None:
    """Wayback bytes result after a transport failure; None when not attempted/found."""
    if config.wayback_fallback:
        return fetch_bytes_via_wayback(client, url, config, state)
    return None
