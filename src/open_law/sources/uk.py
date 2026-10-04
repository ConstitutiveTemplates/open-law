"""legislation.gov.uk adapter — UK legislation as XML and Akoma Ntoso.

The National Archives publishes every UK legislation item as structured
XML (``/data.xml``) and Akoma Ntoso (``/data.akn``) with no registration;
robots.txt allows all paths but asks for ``Crawl-delay: 5``, which the
adapter's ``crawl_delay_seconds`` mirrors. The adapter fetches the XML
rendition and also reports the AKN URL, so downstream consumers can pull
the interoperable format without re-deriving it.

Law identifiers are URL path fragments below the host, e.g.
``ukcm/2023/1`` (a Measure) or ``ukpga/1989/6`` (an Act).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import ClassVar

from defusedxml.ElementTree import fromstring
from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.base import SourceAdapter

__all__ = ["LegislationGovUkAdapter"]

_BASE = "https://www.legislation.gov.uk"


def _child_by_local(parent: ET.Element, local: str) -> ET.Element | None:
    """First child of *parent* whose tag ends with *local* (any namespace)."""
    for child in parent:
        if child.tag.rpartition("}")[2] == local:
            return child
    return None


def _text_of(element: ET.Element | None) -> str | None:
    """Stripped text of *element*, or None when empty/absent."""
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped or None


class LegislationGovUkAdapter(SourceAdapter):
    """Fetch UK legislation from the official legislation.gov.uk API."""

    source_id: ClassVar[str] = "uk"
    name: ClassVar[str] = "legislation.gov.uk (The National Archives)"
    jurisdiction: ClassVar[str] = "GB"
    homepage: ClassVar[str] = "https://www.legislation.gov.uk"
    license_note: ClassVar[str] = "Open Government Licence v3.0"
    crawl_delay_seconds: ClassVar[float] = 5.0
    text_format: ClassVar[str] = "xml"

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one legislation item's metadata by its URL path *law_id*."""
        law_id = law_id.strip("/")
        url = f"{_BASE}/{law_id}/data.xml"
        body = self._get(url)
        try:
            root = fromstring(body)
        except ET.ParseError as exc:
            msg = f"legislation.gov.uk returned malformed XML for {law_id!r}"
            raise ValueError(msg) from exc
        uri = root.attrib.get("DocumentURI") or url
        metadata = _child_by_local(root, "Metadata")
        title = _text_of(_child_by_local(metadata, "title") if metadata is not None else None)
        extras = [
            ("legislation_type", _root_type(root)),
            ("publisher", _text_of(_child_by_local(metadata, "publisher")) if metadata is not None else None),
            ("provisions", root.attrib.get("NumberOfProvisions")),
            ("valid_from", _text_of(_child_by_local(metadata, "valid")) if metadata is not None else None),
        ]
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=law_id,
            title=title or uri,
            url=uri,
            language=_text_of(_child_by_local(metadata, "language") if metadata is not None else None),
            modified=_text_of(_child_by_local(metadata, "modified") if metadata is not None else None),
            text_url=url,
            akn_url=f"{_BASE}/{law_id}/data.akn",
            extras=tuple((key, value) for key, value in extras if value),
        )

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Not offered: the API is id-addressed; discovery is via sitemaps.

        legislation.gov.uk publishes per-type sitemaps (linked from its
        robots.txt) and a human search UI; neither is a stable machine
        search API this adapter can call politely yet.
        """
        msg = (
            "legislation.gov.uk offers no machine search API "
            f"(query={query!r}, limit={limit}); fetch by id "
            "(e.g. 'ukpga/1989/6') or browse the sitemaps linked from robots.txt"
        )
        raise NotAvailableBySourceError(msg)


def _root_type(root: ET.Element) -> str | None:
    """The root's first structural child (Primary/Secondary/...) as the type."""
    for child in root:
        if child.tag.rpartition("}")[2] != "Metadata":
            return child.tag.rpartition("}")[2]
    return None
