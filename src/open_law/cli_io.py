"""CLI output plumbing: printing JSON, laws, and Wayback provenance.

Every adapter-bound command funnels through here for its terminal
output: :func:`print_json` for machine-readable payloads,
:func:`maybe_print_wayback` for the archive-provenance line on stderr.
Keeping output in one module keeps the five source commands
(:mod:`open_law.cli_sources`) and the dispatch in
:mod:`open_law.__main__` free of formatting details.
"""

from __future__ import annotations

import json
import sys

from open_law.sources.adapter import SourceAdapter

__all__ = ["maybe_print_wayback", "print_json"]


def print_json(payload: object) -> None:
    """Print *payload* as readable, non-escaped JSON."""
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def maybe_print_wayback(adapter: SourceAdapter) -> None:
    """When the adapter's last fetch used Wayback, report it on stderr."""
    result = getattr(adapter.fetcher, "last_result", None)
    if result is not None and getattr(result, "from_wayback", False):
        ts = getattr(result, "wayback_timestamp", None) or ""
        url = getattr(result, "wayback_url", None) or ""
        msg = f"from Wayback Machine: {url}"
        if ts:
            msg += f" (timestamp {ts})"
        print(msg, file=sys.stderr)
