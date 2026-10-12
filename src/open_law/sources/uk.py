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

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.base import SourceAdapter
from open_law.sources.base import child_by_local
from open_law.sources.base import parse_xml
from open_law.sources.base import xml_text

__all__ = ["LegislationGovUkAdapter"]

_BASE = "https://www.legislation.gov.uk"


def _metadata(root: ET.Element) -> ET.Element | None:
    """The document's ``Metadata`` element (any namespace), if present."""
    return child_by_local(root, "Metadata")


def _meta_text(root: ET.Element, local: str) -> str | None:
    """Stripped ``Metadata/<local>`` text, or None when empty/absent."""
    return xml_text(child_by_local(_metadata(root), local))


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
        root = parse_xml(body, f"legislation.gov.uk returned malformed XML for {law_id!r}")
        uri = root.attrib.get("DocumentURI") or url
        title = _meta_text(root, "title")
        extras = [
            ("legislation_type", _root_type(root)),
            ("publisher", _meta_text(root, "publisher")),
            ("provisions", root.attrib.get("NumberOfProvisions")),
            ("valid_from", _meta_text(root, "valid")),
        ]
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=law_id,
            title=title or uri,
            url=uri,
            language=_meta_text(root, "language"),
            modified=_meta_text(root, "modified"),
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
