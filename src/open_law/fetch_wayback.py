"""Wayback Machine fallback for the polite fetcher.

When ``FetchConfig.wayback_fallback`` is on, network errors
(``httpx.HTTPError``) or 5xx responses fall back to the Wayback
availability API (4xx never does — the charter forbids bypassing
access control). Carries snapshot URL/timestamp provenance on
:class:`open_law.fetch_models.FetchResult` so the CLI can report it.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import cast

import httpx

from open_law.fetch_cache import write_cached_body
from open_law.fetch_models import FetchConfig
from open_law.fetch_models import FetchResult

__all__ = [
    "closest_snapshot",
    "fetch_via_wayback",
    "query_wayback",
    "wayback_for_error_status",
    "wayback_on_transport_error",
]


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


def fetch_via_wayback(
    client: httpx.Client,
    url: str,
    config: FetchConfig,
    request_counts: dict[str, int],
) -> FetchResult | None:
    """Try the Wayback Machine for *url*; None when unavailable."""
    snap_url, timestamp = query_wayback(client, url, config)
    if snap_url is None:
        return None
    try:
        resp = client.get(snap_url, timeout=config.timeout_seconds)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    text = resp.text
    write_cached_body(url, text, config)
    # Count the snapshot fetch toward the wayback host budget (best-effort).
    try:
        host = urllib.parse.urlsplit(snap_url).netloc
        request_counts[host] = request_counts.get(host, 0) + 1
    except Exception:
        pass
    return FetchResult(text=text, url=url, from_wayback=True, wayback_url=snap_url, wayback_timestamp=timestamp)


def wayback_for_error_status(
    client: httpx.Client,
    url: str,
    response: httpx.Response,
    config: FetchConfig,
    request_counts: dict[str, int],
) -> FetchResult | None:
    """Wayback result for a 5xx *response*; else raise; None on success."""
    if response.status_code >= 500 and config.wayback_fallback:
        wb = fetch_via_wayback(client, url, config, request_counts)
        if wb is not None:
            return wb
    response.raise_for_status()
    return None


def wayback_on_transport_error(
    client: httpx.Client,
    url: str,
    config: FetchConfig,
    request_counts: dict[str, int],
) -> FetchResult | None:
    """Wayback result after a transport failure; None when not attempted/found."""
    if config.wayback_fallback:
        return fetch_via_wayback(client, url, config, request_counts)
    return None
