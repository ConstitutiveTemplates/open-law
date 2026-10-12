"""On-disk GET cache for the polite fetcher.

Responses are keyed by URL hash under ``FetchConfig.cache_dir`` and
honour ``FetchConfig.cache_ttl_seconds``. Writes are best-effort:
disk errors are ignored so a read-only checkout can still fetch.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import cast

from open_law.fetch_models import FetchConfig

__all__ = ["cache_path", "read_cached_body", "write_cached_body"]


def cache_path(url: str, cache_dir: Path) -> Path:
    """The cache file holding the GET body for *url*."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return cache_dir / f"{digest}.json"


def write_cached_body(url: str, text: str, config: FetchConfig) -> None:
    """Persist a GET body for *url*; best-effort (disk errors are ignored)."""
    try:
        config.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_path(url, config.cache_dir)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"url": url, "fetched_at": time.time(), "text": text}),
            encoding="utf-8",
        )
        tmp.replace(cache_file)
    except OSError:
        pass


def read_cached_body(url: str, config: FetchConfig) -> str | None:
    """Fresh cached body for *url*, or None on miss/expiry/corruption."""
    cache_file = cache_path(url, config.cache_dir)
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
