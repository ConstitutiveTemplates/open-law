"""Texas statutes adapter — Business & Commerce style chapter texts and TCAS search.

The Texas Constitution and Statutes site (``statutes.capitol.texas.gov``)
is a client-side Angular app, but its documents are plain static files on
the Texas-CAS file server (``tcss.legis.texas.gov/resources``) and its
search is a key-free JSON API (``tcss.legis.texas.gov/api``) — both
reverse-engineered from the shipped JS bundles, both reachable without a
browser (verified 2026-10-11). Law identifiers are
``<CODE>.<chapter>`` (``BC.503`` = Business & Commerce Code Chapter 503,
Biometric Identifiers); the file server serves the chapter HTML and
``fetch`` points ``text_url`` at it, which :meth:`full_text` strips to
plain text via the ``html`` format.

Channel notes (verified 2026-10-11): ``statutes.capitol.texas.gov``
serves an empty ``robots.txt`` (HTTP 200, allow all); the
``tcss.legis.texas.gov`` API/file hosts serve no robots.txt (404 —
absent means allowed, ``crawl_delay_seconds`` stays conservative at
2.0). Chapter files are small (BC.503 ~9 KB). Per-section anchors
(``#503.001``) address single sections inside the chapter text.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import ClassVar

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import SourceAdapter
from open_law.sources.base import clamp_limit
from open_law.sources.base import decode_json
from open_law.sources.base import strip_markup

__all__ = ["TexasStatutesAdapter"]

_SITE = "https://statutes.capitol.texas.gov"
_API = "https://tcss.legis.texas.gov/api"
_FILES = "https://tcss.legis.texas.gov/resources"

_ID_RE = re.compile(r"^([A-Za-z]{2})\.(\d+)(?:\.(\d+[A-Za-z]?))?$")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_CHAPTER_RE = re.compile(r"\|([A-Z]{2})\.(\d+)\s*(?:&|$)")


def _chapter_parts(law_id: str) -> tuple[str, str] | None:
    """(CODE, chapter) from ``law_id`` (``BC.503``, ``bc.503.001`` both work)."""
    match = _ID_RE.match(law_id.strip())
    if match is None:
        return None
    return match.group(1).upper(), match.group(2)


class TexasStatutesAdapter(SourceAdapter):
    """Search and fetch Texas statutes via the TCAS JSON API + file server."""

    source_id: ClassVar[str] = "us-tx"
    name: ClassVar[str] = "Texas Constitution and Statutes (Texas Legislature)"
    jurisdiction: ClassVar[str] = "US-TX"
    homepage: ClassVar[str] = "https://statutes.capitol.texas.gov"
    license_note: ClassVar[str] = "Texas government work — public information (Texas Public Information Act)"
    crawl_delay_seconds: ClassVar[float] = 2.0
    text_format: ClassVar[str] = "html"

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Full-text search across all Texas codes (page 1 of TCAS results)."""
        size = clamp_limit(limit)
        url = f"{_API}/TCASSearch/GetPage/1/ZZ/{urllib.parse.quote(query)}"
        body = self._get(url)
        decoded = decode_json(body, f"TCAS returned malformed JSON for query {query!r}")
        rows = decoded if isinstance(decoded, list) else []
        summaries: list[LawSummary] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = row.get("Title")
            viewer = row.get("DocViewer")
            if not isinstance(title, str) or not isinstance(viewer, str):
                continue
            match = _CHAPTER_RE.search(urllib.parse.unquote(viewer))
            if match is None:
                continue
            law_id = f"{match.group(1)}.{match.group(2)}"
            summaries.append(
                LawSummary(
                    source=self.source_id,
                    jurisdiction=self.jurisdiction,
                    law_id=law_id,
                    title=title.strip(),
                    url=f"{_SITE}/Docs/{match.group(1)}/htm/{law_id}.htm",
                    extras=(("document_code", str(row.get("DocumentCode", match.group(1)))),),
                )
            )
            if len(summaries) >= size:
                break
        return summaries

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one chapter's static HTML as a :class:`Law`.

        *law_id* is ``<CODE>.<chapter>`` (``BC.503``); a trailing
        section (``BC.503.001``) narrows the landing anchor but fetches
        the same chapter file — sections share one document on the file
        server.
        """
        parts = _chapter_parts(law_id)
        if parts is None:
            msg = f"Unrecognised Texas statute id {law_id!r} (expected e.g. 'BC.503', 'BC.503.001')"
            raise ValueError(msg)
        code, chapter = parts
        law_key = f"{code}.{chapter}"
        text_url = f"{_FILES}/{code}/htm/{law_key}.htm"
        body = self._get(text_url)
        title_m = _TITLE_RE.search(body)
        title = strip_markup(title_m.group(1)) if title_m else None
        url = f"{_SITE}/Docs/{code}/htm/{law_key}.htm"
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=law_key,
            title=title or law_key,
            url=url,
            language="eng",
            text_url=text_url,
            extras=(("format", "tcas-html"), ("code", code), ("chapter", chapter)),
        )
