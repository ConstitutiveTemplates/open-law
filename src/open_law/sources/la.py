"""Lao Official Gazette adapter — Laos's official legal gazette.

laoofficialgazette.gov.la serves each legal document as a
server-rendered page at ``index.php?r=site/display&id=<id>`` whose
metadata arrives as ``<div class="row"><strong>label:</strong> value``
blocks (title, document type, issuing agency, dates) and whose full
text is a linked PDF under ``/kcfinder/upload/files/``. robots.txt is
absent, so the fetcher's defaults govern.

The document title lives only in those blocks (the ``<title>`` tag is
a generic "Laogazette - Display Site"), so the parser reads the rows
and maps the Lao labels; unknown labels become extras. Dates are kept
exactly as printed (DD-MM-YYYY) — the model's ``promulgation_date``
stays empty rather than silently reformatting a non-ISO date.
"""

from __future__ import annotations

import re
from typing import ClassVar

from typing_extensions import override

from open_law.dates import to_iso_date
from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.base import SourceAdapter

__all__ = ["LaoGazetteAdapter"]

_BASE = "https://laoofficialgazette.gov.la"

_ROW_RE = re.compile(r"<div class=\"row\">\s*<strong>[^<:]*:?\s*</strong>(.*?)</div>", re.DOTALL | re.IGNORECASE)
_LABEL_RE = re.compile(r"<strong>(.*?)</strong>", re.DOTALL | re.IGNORECASE)
_PDF_RE = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.IGNORECASE)

# Lao row labels -> (model field, extras key).
_LABEL_MAP: dict[str, tuple[str | None, str]] = {
    "ຫົວຂໍ້": (None, "title"),
    "ປະເພດ ນິຕິກໍາ": (None, "document_type"),
    "ອອກໂດຍ": (None, "issued_by"),
    "ພາກສ່ວນຮັບຜິດຊອບ": (None, "responsible_body"),
    "ວັນທີ່ ນິຕິກໍາ": (None, "document_date"),
    "ເຜີຍແຜ່ລົງ ຈົດໝາຍເຫດ ວັນທີ່": (None, "gazette_date"),
}


def _strip_tags(html: str) -> str:
    """*html* with tags removed and whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class LaoGazetteAdapter(SourceAdapter):
    """Fetch Lao gazette documents by numeric display id."""

    source_id: ClassVar[str] = "la"
    name: ClassVar[str] = "Lao Official Gazette"
    jurisdiction: ClassVar[str] = "LA"
    homepage: ClassVar[str] = "https://laoofficialgazette.gov.la"
    license_note: ClassVar[str] = "Government of Laos publication"
    crawl_delay_seconds: ClassVar[float] = 2.0
    text_format: ClassVar[str] = "pdf"

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one gazette document's metadata page."""
        number_match = re.search(r"\d+", law_id)
        number = number_match.group(0) if number_match else ""
        if not number:
            msg = f"{law_id!r} is not a Laogazette display id (expected e.g. '2143')"
            raise ValueError(msg)
        url = f"{_BASE}/index.php?r=site/display&id={number}"
        body = self._get(url)
        fields: dict[str, str] = {}
        for row_match in _ROW_RE.finditer(body):
            label_match = _LABEL_RE.search(row_match.group(0))
            label = _strip_tags(label_match.group(1)).rstrip(": ").strip() if label_match else ""
            value = _strip_tags(row_match.group(1))
            if label and value:
                fields[label] = value
        title = fields.get("ຫົວຂໍ້", "")
        if not title:
            msg = f"gazette id {number!r} is not a legal document page"
            raise LookupError(msg)
        pdf_match = _PDF_RE.search(body)
        pdf_url = f"{_BASE}{pdf_match.group(1)}" if pdf_match else None
        extras = [(key, fields[label]) for label, (_, key) in _LABEL_MAP.items() if key != "title" and label in fields]
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=number,
            title=title,
            promulgation_date=to_iso_date(fields.get("ວັນທີ່ ນິຕິກໍາ"), dayfirst=True),
            language="lo",
            url=url,
            text_url=pdf_url,
            extras=tuple(extras),
        )

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Not offered: the gazette's listing pages drive the discovery flow.

        Document ids come from the listings at
        ``index.php?r=site/list&legaltype=<type>`` and the homepage's
        recent-documents block; walk those to collect ids, then
        :meth:`fetch` each.
        """
        msg = (
            "laoofficialgazette.gov.la offers no machine search "
            f"(query={query!r}, limit={limit}); fetch by numeric display id "
            "(e.g. '2143') — ids are listed on the site/list pages"
        )
        raise NotAvailableBySourceError(msg)
