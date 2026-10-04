"""Korea 국가법령정보센터 Open API adapter — Korea's official law portal.

law.go.kr allows crawlers outright in robots.txt (``Allow: /`` plus a
sitemap), but its DRF machine interface (``lawSearch.do`` /
``lawService.do``) requires an open-API id (``OC``) bound to the
caller's server IP, issued at openapi.law.go.kr. The id is read from
the ``LAW_KR_OC`` environment variable; without it, search explains the
registration step instead of failing opaquely.

Response tags follow the official Open API specification: a
``LawSearch`` document wraps ``laws/law`` entries whose tags are the
published Korean field names (법령명한글, 법령ID, 공포일자, ...). Field
access is defensive — unknown or absent tags become ``None`` rather
than parse errors.
"""

from __future__ import annotations

import os
import urllib.parse
import xml.etree.ElementTree as ET
from typing import ClassVar

from defusedxml.ElementTree import fromstring
from typing_extensions import override

from open_law.dates import to_iso_date
from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.base import SourceAdapter

__all__ = ["KoreaLawAdapter"]

_BASE = "https://www.law.go.kr/DRF"

# (xml tag, extras key) for fields kept but not modelled globally.
_EXTRAS_TAGS: tuple[tuple[str, str], ...] = (
    ("법령약칭명", "abbreviation"),
    ("법령구분", "category"),
    ("제개정구분", "amendment_kind"),
    ("공포번호", "promulgation_number"),
)


def _text_of(element: ET.Element | None) -> str | None:
    """Stripped text of *element*, or None when empty/absent."""
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped or None


def _child_text(parent: ET.Element, tag: str) -> str | None:
    """Stripped text of *parent*'s first child named *tag*."""
    return _text_of(parent.find(tag))


class KoreaLawAdapter(SourceAdapter):
    """Search Korea's law list via the DRF open API (registration-gated)."""

    source_id: ClassVar[str] = "kr"
    name: ClassVar[str] = "국가법령정보센터 (Ministry of Government Legislation)"
    jurisdiction: ClassVar[str] = "KR"
    homepage: ClassVar[str] = "https://www.law.go.kr"
    license_note: ClassVar[str] = "공공누리 (KOGL, attribution)"
    crawl_delay_seconds: ClassVar[float] = 1.0

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Title-search the law list; requires ``LAW_KR_OC`` in the env."""
        oc = os.environ.get("LAW_KR_OC")
        if not oc:
            msg = (
                "Korea's DRF API needs an open-API id (OC) bound to your "
                "server IP; register at https://openapi.law.go.kr/ and set "
                "the LAW_KR_OC environment variable"
            )
            raise NotAvailableBySourceError(msg)
        url = f"{_BASE}/lawSearch.do?target=law&type=XML&query={urllib.parse.quote(query)}&OC={urllib.parse.quote(oc)}"
        body = self._get(url)
        try:
            root = fromstring(body)
        except ET.ParseError as exc:
            msg = f"law.go.kr returned malformed XML for query {query!r}"
            raise ValueError(msg) from exc
        summaries: list[LawSummary] = []
        for entry in root.findall("laws/law"):
            law_id = _child_text(entry, "법령ID")
            title = _child_text(entry, "법령명한글") or _child_text(entry, "법령명영문")
            if law_id is None or title is None:
                continue
            promulgation_raw = _child_text(entry, "공포일자")
            extras = tuple((key, text) for tag, key in _EXTRAS_TAGS if (text := _child_text(entry, tag)) is not None)
            if promulgation_raw is not None:
                extras = (("promulgation_date_raw", promulgation_raw), *extras)
            summaries.append(
                LawSummary(
                    source=self.source_id,
                    jurisdiction=self.jurisdiction,
                    law_id=law_id,
                    title=title,
                    promulgation_date=to_iso_date(promulgation_raw),
                    url=_child_text(entry, "detailLink"),
                    extras=extras,
                )
            )
        return summaries[: max(1, limit)]

    @override
    def fetch(self, law_id: str) -> Law:
        """Not offered without registration: full text needs the same key.

        The DRF full-text endpoint (``lawService.do``) is gated by the
        same OC id as search; extend this method with its documented
        ``LawService`` parsing once ``LAW_KR_OC`` is configured.
        """
        msg = (
            f"Korea full text for {law_id!r} needs the LAW_KR_OC open-API id "
            "(lawService.do); register at https://openapi.law.go.kr/ — the "
            f"landing page is https://law.go.kr/LSW/lawInfo.do?법령ID={urllib.parse.quote(law_id)}"
        )
        raise NotAvailableBySourceError(msg)
