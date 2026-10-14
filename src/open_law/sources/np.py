"""lawcommission.gov.np adapter — Nepal Law Commission publications.

The commission publishes Nepali acts and related corpus as
server-rendered pages under ``/content/<id>/<slug>`` (the slug is
decorative; ``/content/<id>/`` serves the same page, verified 2026-09).
robots.txt sets ``Crawl-delay: 10`` and disallows nothing — the adapter
mirrors the requested delay. There is no machine API (the homepage's
category indexes are the discovery surface), so the adapter is
id-addressed and ``search`` points at the index pages.
"""

from __future__ import annotations

import re
from typing import ClassVar

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.adapter import NotAvailableBySourceError
from open_law.sources.adapter import SourceAdapter
from open_law.sources.markup import collapse_markup

__all__ = ["NepalLawCommissionAdapter"]

_BASE = "https://lawcommission.gov.np"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
_SITE_SUFFIX = " | Nepal Law Commission"


def _page_title(body: str) -> str:
    """The ``<title>`` text without the site suffix."""
    title_match = _TITLE_RE.search(body)
    title = title_match.group(1).strip() if title_match else ""
    if title.endswith(_SITE_SUFFIX):
        title = title[: -len(_SITE_SUFFIX)].strip()
    return title


def _content_number(law_id: str) -> str:
    """The numeric content id in *law_id*, or '' when there is none."""
    number_match = re.search(r"\d+", law_id)
    return number_match.group(0) if number_match else ""


class NepalLawCommissionAdapter(SourceAdapter):
    """Fetch Nepal Law Commission content pages by numeric content id."""

    source_id: ClassVar[str] = "np"
    name: ClassVar[str] = "Nepal Law Commission"
    jurisdiction: ClassVar[str] = "NP"
    homepage: ClassVar[str] = "https://lawcommission.gov.np"
    license_note: ClassVar[str] = "Nepal Law Commission publication"
    crawl_delay_seconds: ClassVar[float] = 10.0

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one content page and extract its title."""
        number = _content_number(law_id)
        if not number:
            msg = f"{law_id!r} is not a Nepal Law Commission content id (expected e.g. '13535')"
            raise ValueError(msg)
        url = f"{_BASE}/content/{number}/"
        body = self._get(url)
        title = _page_title(body)
        if title in ("", "404"):
            msg = f"no content with id {number!r} on lawcommission.gov.np"
            raise LookupError(msg)
        h1_match = _H1_RE.search(body)
        h1 = collapse_markup(h1_match.group(1)) if h1_match else ""
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=number,
            title=h1 or title,
            url=url,
            text_url=url,
            extras=(("content_id", number),),
        )

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Not offered: discovery is via the server-rendered category indexes.

        The homepage links categories (``/category/<id>``) whose pages
        list acts as ``/content/<id>/<slug>`` links; walk those to collect
        ids, then :meth:`fetch` each.
        """
        msg = (
            "lawcommission.gov.np offers no machine search "
            f"(query={query!r}, limit={limit}); fetch by numeric content id "
            "(e.g. '13535') — ids are listed in the /category/<id> indexes"
        )
        raise NotAvailableBySourceError(msg)
