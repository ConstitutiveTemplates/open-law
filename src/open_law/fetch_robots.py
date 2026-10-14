"""robots.txt gating for the polite fetcher.

The parser is fetched once per host and stored on that host's
:class:`~open_law.fetch_state.HostState`: robots.txt barely moves, and
re-fetching it per page would itself be impolite load.
"""

from __future__ import annotations

import urllib.parse
import urllib.robotparser

import httpx

__all__ = ["load_robots_parser"]


def load_robots_parser(page_url: str, client: httpx.Client) -> urllib.robotparser.RobotFileParser:
    """Fetch and parse the site's robots.txt for *page_url*'s origin.

    The caller decides when to call this (robots.txt is the first request
    to a host) and where to cache the result. Transport failures yield an
    empty (fully permissive) parser rather than blocking the fetch.
    """
    parts = urllib.parse.urlsplit(page_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(f"{origin}/robots.txt")
    try:
        response = client.get(f"{origin}/robots.txt", timeout=10.0)
        lines = response.text.splitlines() if response.status_code == 200 else []
    except httpx.HTTPError:
        lines = []
    parser.parse(lines)
    return parser
