"""On-disk GET cache for the polite fetcher.

Responses are keyed by a hash of the URL **and** the content-negotiation
headers the request carried, under ``FetchConfig.cache_dir`` (the
platform user cache by default), and honour
``FetchConfig.cache_ttl_seconds``. EUR-Lex serves RDF or HTML from one
URL depending on ``Accept``, so keying on the URL alone would hand an
HTML body to a caller that asked for RDF.

Text bodies are stored as JSON with an explicit ``fetched_at``; binary
bodies (PDFs, other documents) are stored beside them as ``.bin`` and
dated by the file's mtime, so bytes never round-trip through UTF-8.
Writes are best-effort: disk errors are ignored so a read-only checkout
can still fetch.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from open_law.fetch_models import FetchConfig

__all__ = [
    "cache_key",
    "cache_path",
    "read_cached_body",
    "read_cached_bytes",
    "write_cached_body",
    "write_cached_bytes",
]


def cache_key(url: str, headers: Mapping[str, str] | None = None) -> str:
    """The cache digest for *url* as requested under *headers*."""
    negotiated = sorted((key.lower(), value) for key, value in (headers or {}).items())
    material = f"{url}\n{json.dumps(negotiated, ensure_ascii=False)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def cache_path(
    url: str,
    cache_dir: Path,
    headers: Mapping[str, str] | None = None,
    *,
    suffix: str = ".json",
) -> Path:
    """The cache file holding the response for *url* (``.json`` or ``.bin``)."""
    return cache_dir / f"{cache_key(url, headers)}{suffix}"


def write_cached_body(url: str, text: str, config: FetchConfig, headers: Mapping[str, str] | None = None) -> None:
    """Persist a text body for *url*; best-effort (disk errors are ignored)."""
    try:
        config.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_path(url, config.cache_dir, headers)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"url": url, "fetched_at": time.time(), "text": text}),
            encoding="utf-8",
        )
        tmp.replace(cache_file)
    except OSError:
        pass


def read_cached_body(url: str, config: FetchConfig, headers: Mapping[str, str] | None = None) -> str | None:
    """Fresh cached text body for *url*, or None on miss/expiry/corruption."""
    cache_file = cache_path(url, config.cache_dir, headers)
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


def write_cached_bytes(url: str, data: bytes, config: FetchConfig, headers: Mapping[str, str] | None = None) -> None:
    """Persist a binary body for *url* verbatim; best-effort.

    The bytes are written as-is (no encoding step), so a PDF or any other
    non-UTF-8 payload comes back byte-identical.
    """
    try:
        config.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_path(url, config.cache_dir, headers, suffix=".bin")
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(cache_file)
    except OSError:
        pass


def read_cached_bytes(url: str, config: FetchConfig, headers: Mapping[str, str] | None = None) -> bytes | None:
    """Fresh cached binary body for *url*, or None on miss/expiry.

    Binary entries carry no JSON envelope; their mtime is the fetch stamp.
    """
    cache_file = cache_path(url, config.cache_dir, headers, suffix=".bin")
    try:
        stamp = cache_file.stat().st_mtime
    except OSError:
        return None
    if time.time() - stamp >= config.cache_ttl_seconds:
        return None
    try:
        return cache_file.read_bytes()
    except OSError:
        return None
