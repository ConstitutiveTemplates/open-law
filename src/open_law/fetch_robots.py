"""robots.txt gating for the polite fetcher.

The parser is fetched once per origin and reused: robots.txt barely
moves, and re-fetching it per page would itself be impolite load.
"""

from __future__ import annotations

import urllib.parse
import urllib.robotparser

import httpx

__all__ = ["load_robots_parser"]


def load_robots_parser(
    page_url: str,
    client: httpx.Client,
    cache: dict[str, urllib.robotparser.RobotFileParser],
) -> urllib.robotparser.RobotFileParser:
    """Fetch (once per origin) and parse the site's robots.txt.

    *cache* maps origins to parsed parsers; transport failures yield an
    empty (fully permissive) parser rather than blocking the fetch.
    """
    parts = urllib.parse.urlsplit(page_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    cached = cache.get(origin)
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
    cache[origin] = parser
    return parser
