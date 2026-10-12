"""Germany adapter — federal statutes from Gesetze im Internet.

The Federal Ministry of Justice / Federal Office of Justice portal at
``gesetze-im-internet.de`` publishes every federal act as a per-law
folder: ``/<dir>/index.html`` is the table of contents (full HTML at
``/<dir>/<DOKNR>.html``, print PDF and ``xml.zip`` linked from the
same page). The alphabetical ``Teilliste_<LETTER>.html`` indexes map
abbreviation (``BGB``) to folder (``bgb``) and full title.

Channel notes (verified 2026-10-11): robots.txt is ``User-agent: *
Disallow:`` (empty = allow all, HTTP 200); pages are small except the
big codes (BGB index ~486 KB, full HTML ~3 MB — budget-aware fetchers
still fine); per-law ``xml.zip`` holds the GII DTD XML. Index pages are
``iso-8859-1``; the fetcher decodes response bodies for us.
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
from open_law.sources.base import strip_markup

__all__ = ["GesetzeImInternetAdapter"]

_BASE = "https://www.gesetze-im-internet.de"
_HUMAN = _BASE

_DIR_RE = re.compile(r"^[a-z0-9_][a-z0-9_.-]*$")
_ENTRY_RE = re.compile(
    r'<p><a href="\./([a-z0-9_.-]+)/index\.html"><abbr title="([^"]+)">\s*([^<]+?)\s*</abbr></a><br\s*/>\s*(.*?)'
    r"(?:&nbsp;|<a href=|</p>)",
    re.DOTALL,
)
_H1_RE = re.compile(r'<h1 class="headline">(.*?)</h1>', re.DOTALL)
_META_RE = re.compile(
    r'<meta name="htdig-keywords" content="([^-"]+)\s*-\s*nichtamtliches Inhaltsverzeichnis\s*-\s*([^"]+)"'
)
_FULL_RE = re.compile(r'<a href="([A-Z0-9][A-Za-z0-9.-]*\.html)"><abbr>HTML</abbr></a>')


class GesetzeImInternetAdapter(SourceAdapter):
    """Search and fetch German federal statutes via Gesetze im Internet."""

    source_id: ClassVar[str] = "de"
    name: ClassVar[str] = "Gesetze im Internet (BMJ/BfJ)"
    jurisdiction: ClassVar[str] = "DE"
    homepage: ClassVar[str] = "https://www.gesetze-im-internet.de"
    license_note: ClassVar[str] = (
        "Gesetze im Internet — federal statutes; official publication, no additional licence terms stated"
    )
    crawl_delay_seconds: ClassVar[float] = 2.0
    text_format: ClassVar[str] = "html"

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Title/abbreviation search over the alphabetical law index.

        The portal has no machine search endpoint; the static
        ``Teilliste_<LETTER>.html`` indexes (one GET, letter from the
        query's first letter) are the machine channel. Matches against
        the abbreviation, the full title, and the display title.
        """
        size = clamp_limit(limit)
        first = next((c for c in query.strip().upper() if c.isalpha()), None)
        if first is None:
            return []
        body = self._get(f"{_BASE}/Teilliste_{urllib.parse.quote(first)}.html")
        needle = query.strip().lower()
        summaries: list[LawSummary] = []
        for match in _ENTRY_RE.finditer(body):
            folder, full, abbrev, rest = match.group(1), match.group(2), match.group(3), match.group(4)
            title = strip_markup(rest, unescape=True) or strip_markup(full, unescape=True) or folder
            abbrev_clean = strip_markup(abbrev, unescape=True) or folder.upper()
            full_clean = strip_markup(full, unescape=True) or title
            haystack = f"{abbrev_clean.lower()} {full_clean.lower()} {(title or '').lower()}"
            if needle not in haystack:
                continue
            summaries.append(
                LawSummary(
                    source=self.source_id,
                    jurisdiction=self.jurisdiction,
                    law_id=folder,
                    title=title or abbrev_clean,
                    url=f"{_BASE}/{folder}/index.html",
                    extras=(("abbrev", abbrev_clean), ("full_title", full_clean)),
                )
            )
            if len(summaries) >= size:
                break
        return summaries

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one act's table-of-contents page as a :class:`Law`.

        *law_id* is the portal folder (``bgb``, ``stgb``); the
        abbreviation case (``BGB``) is tolerated. ``text_url`` is the
        full-HTML Gesamtausgabe linked from the index page, which
        :meth:`full_text` strips to plain text.
        """
        folder = law_id.strip().lower()
        if not _DIR_RE.match(folder):
            msg = f"Unrecognised Gesetze-im-Internet id {law_id!r} (expected a folder like 'bgb', 'stgb')"
            raise ValueError(msg)
        index_url = f"{_BASE}/{folder}/index.html"
        body = self._get(index_url)
        h1 = _H1_RE.search(body)
        meta = _META_RE.search(body)
        title = strip_markup(h1.group(1), unescape=True) if h1 else None
        if title is None:
            title = strip_markup(meta.group(2), unescape=True) if meta else folder
        abbrev = strip_markup(meta.group(1), unescape=True) if meta else folder.upper()
        full = _FULL_RE.search(body)
        text_url = f"{_BASE}/{folder}/{full.group(1)}" if full else index_url
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=folder,
            title=title or folder,
            url=index_url,
            language="deu",
            text_url=text_url,
            extras=(("abbrev", abbrev or folder.upper()), ("format", "gii-html")),
        )
