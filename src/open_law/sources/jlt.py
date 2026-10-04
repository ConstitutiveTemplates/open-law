"""Japan official English translations — JLT (Japanese Law Translation) adapter.

The Ministry of Justice's Japanese Law Translation Database System
(``japaneselawtranslation.go.jp``) is the official English side of
Japan's statute book: professional human translations of the same laws
the e-Gov ``jp`` adapter indexes. Law identifiers are JLT numeric ids
(``4913`` = Labor Standards Act, ``4848`` = Civil Code Parts I-III) -
different from e-Gov ``law_id``s; the two id spaces map by statute, and
the ``jp`` adapter's search resolves the e-Gov id for a title.

Machine surfaces (verified 2026-10-04): the per-law view page
``/en/laws/view/<id>`` is 200, and its ``download`` links expose a
bilingual **TMX 1.4 file** (``/en/laws/download/<id>/23/<key>.tmx`` —
translation memory with ``<tu>`` ja/en pairs, e.g. 556 pairs for the
Labor Standards Act). The free-text search form is CSRF-gated and
returns 403 to machines, so ``search`` is deliberately not offered —
fetch by JLT id instead (the `/ja/laws` index and per-law pages are the
human discovery surface).
"""

from __future__ import annotations

import re
from typing import ClassVar

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.base import SourceAdapter

__all__ = ["JltAdapter"]

_BASE = "https://www.japaneselawtranslation.go.jp"
_HUMAN = _BASE

_ID_RE = re.compile(r"^\d+$")
_TMX_RE = re.compile(r"download/(\d+)/23/([A-Za-z0-9._-]+\.tmx)")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_PDF_RE = re.compile(r"download/(\d+)/14/([A-Za-z0-9._-]+\.pdf)")
_TXT_RE = re.compile(r"download/(\d+)/13/([A-Za-z0-9._-]+\.txt)")
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(text: str | None) -> str | None:
    if text is None:
        return None
    clean = _TAG_RE.sub("", text).strip()
    return clean or None


class JltAdapter(SourceAdapter):
    """Fetch JLT's official English translations as TMX translation memory."""

    source_id: ClassVar[str] = "jlt"
    name: ClassVar[str] = "Japanese Law Translation (Ministry of Justice)"
    jurisdiction: ClassVar[str] = "JP"
    homepage: ClassVar[str] = "https://www.japaneselawtranslation.go.jp"
    license_note: ClassVar[str] = (
        "Public Data License 1.0 (terms at /en/index/terms) — "
        "Ministry of Justice ©; English translations of Japanese statutes"
    )
    crawl_delay_seconds: ClassVar[float] = 2.0
    text_format: ClassVar[str] = "tmx"

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Not offered: JLT's free-text search is CSRF-gated (403 to machines).

        Fetch by JLT id instead — e.g. ``4913`` for the Labor Standards Act —
        or use the ``jp`` adapter to resolve an e-Gov ``law_id`` by title,
        then look up the corresponding JLT id in the index.
        """
        msg = (
            "JLT search is CSRF-gated and not a machine channel "
            f"(query={query!r}, limit={limit}); fetch by JLT id "
            "(e.g. '4913' for the Labor Standards Act) from the index at "
            "https://www.japaneselawtranslation.go.jp/en/laws"
        )
        raise NotAvailableBySourceError(msg)

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one law's official English translation as TMX.

        *law_id* is the JLT numeric id (``4913``, ``4848``). The view
        page's download links expose the bilingual TMX 1.4 file; the
        ``text_url`` is the human view page and ``extras`` carries the
        TMX path plus PDF/TXT alternates when present.
        """
        lid = law_id.strip().removeprefix("jlt").removeprefix("/")
        if not _ID_RE.match(lid):
            msg = f"Unrecognised JLT id {law_id!r} (expected a numeric id like '4913')"
            raise ValueError(msg)
        view_url = f"{_BASE}/en/laws/view/{lid}"
        body = self._get(view_url)
        title_m = _TITLE_RE.search(body)
        raw = _strip(title_m.group(1)) if title_m else None
        title = (raw or lid).split(" - ")[0].strip()  # drop " - Japanese/English - Japanese Law Translation"
        tmx = _TMX_RE.search(body)
        pdf = _PDF_RE.search(body)
        txt = _TXT_RE.search(body)
        extras: list[tuple[str, str]] = [("format", "jlt-tmx")]
        if pdf:
            extras.append(("pdf_url", f"{_BASE}/en/laws/{pdf.group(0)}"))
        if txt:
            extras.append(("txt_url", f"{_BASE}/en/laws/{txt.group(0)}"))
        if not tmx:
            msg = f"JLT page for {lid} has no TMX download (older translation?)"
            raise NotAvailableBySourceError(msg)
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=lid,
            title=title or lid,
            url=view_url,
            language="eng",
            modified=None,  # TMX carries creationdate inside; page has no field
            text_url=f"{_BASE}/en/laws/{tmx.group(0)}",
            extras=tuple(extras),
        )
