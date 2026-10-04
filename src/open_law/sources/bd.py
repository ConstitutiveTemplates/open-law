"""bdlaws adapter — Bangladesh's official laws database (English texts).

bdlaws.minlaw.gov.bd publishes the laws of Bangladesh (including the
colonial-era corpus, in English) as server-rendered HTML with no
robots.txt restrictions — but the pages are **UTF-16 encoded**, which
the polite fetcher's charset detection handles transparently. The
chronological index is JS-rendered, so the adapter is id-addressed:
``law_id`` is the numeric act id of ``act-details-<id>.html``.

There is no machine API to prefer (probed 2026-09), so this is the
charter's "scraping last": plain HTML, fetched politely, one page per
call. Parsing is deliberately regex-based — the two fields the adapter
needs (``<title>`` and the ``Description`` meta) are stable strings,
and pulling in an HTML dependency for that would be disproportionate.
"""

from __future__ import annotations

import re
from typing import ClassVar

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.base import SourceAdapter

__all__ = ["BangladeshLawsAdapter"]

_BASE = "https://bdlaws.minlaw.gov.bd"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_PREAMBLE_RE = re.compile(r'name="Description"\s+content="([^"]*)"', re.IGNORECASE)
_YEAR_RE = re.compile(r",\s*(\d{4})\s*$")


def _act_number(law_id: str) -> str:
    """The numeric act id from *law_id* ('43' or 'act-details-43.html')."""
    number = re.sub(r"\D", "", law_id)
    if not number:
        msg = f"{law_id!r} is not a bdlaws act id (expected e.g. '43')"
        raise ValueError(msg)
    return number


class BangladeshLawsAdapter(SourceAdapter):
    """Fetch Bangladesh laws from bdlaws by numeric act id."""

    source_id: ClassVar[str] = "bd"
    name: ClassVar[str] = "bdlaws (Ministry of Law, Justice and Parliamentary Affairs)"
    jurisdiction: ClassVar[str] = "BD"
    homepage: ClassVar[str] = "https://bdlaws.minlaw.gov.bd"
    license_note: ClassVar[str] = "Government of Bangladesh publication (no explicit reuse licence)"
    crawl_delay_seconds: ClassVar[float] = 2.0

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one act's page and extract its title and preamble."""
        number = _act_number(law_id)
        url = f"{_BASE}/act-details-{number}.html"
        body = self._get(url)
        title_match = _TITLE_RE.search(body)
        title = title_match.group(1).strip() if title_match else ""
        if title in ("", "404"):
            msg = f"no act with id {number!r} on bdlaws"
            raise LookupError(msg)
        preamble_match = _PREAMBLE_RE.search(body)
        preamble = preamble_match.group(1).strip() if preamble_match else ""
        year_match = _YEAR_RE.search(title)
        extras = [("act_number", number)]
        if preamble:
            extras.append(("preamble", preamble))
        if year_match:
            extras.append(("year", year_match.group(1)))
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=number,
            title=title,
            url=url,
            language="en",
            text_url=url,
            extras=tuple(extras),
        )

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Not offered: the chronological index is JS-rendered.

        There is no machine search endpoint; ids come from the human
        index at ``laws-of-bangladesh-chronological-index.html``.
        """
        msg = (
            "bdlaws offers no machine search "
            f"(query={query!r}, limit={limit}); fetch by numeric act id "
            "(e.g. '43') — ids are listed in the site's chronological index"
        )
        raise NotAvailableBySourceError(msg)
