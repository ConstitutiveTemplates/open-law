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
from open_law.models import Provision
from open_law.sources.adapter import NotAvailableBySourceError
from open_law.sources.adapter import SourceAdapter
from open_law.sources.parsing import child_by_local
from open_law.sources.parsing import pairs
from open_law.sources.parsing import parse_xml
from open_law.sources.parsing import xml_text

__all__ = ["LegislationGovUkAdapter"]

_BASE = "https://www.legislation.gov.uk"


def _metadata(root: ET.Element) -> ET.Element | None:
    """The document's ``Metadata`` element (any namespace), if present."""
    return child_by_local(root, "Metadata")


def _meta_text(root: ET.Element, local: str) -> str | None:
    """Stripped ``Metadata/<local>`` text, or None when empty/absent."""
    return xml_text(child_by_local(_metadata(root), local))


def _local(element: ET.Element) -> str:
    """Tag name without its namespace."""
    return element.tag.rpartition("}")[2]


def _section_text(section: ET.Element) -> str:
    """Own text of a section: number + prose, excluding nested subsections.

    ``BlockAmendment`` subtrees are quoted insert text (an amendment
    quoting the provisions it inserts), not live structure, so they
    contribute neither own text nor children.
    """
    own_level = _local(section)[1]
    parts: list[str] = []
    for child in list(section):
        name = _local(child)
        if name == "BlockAmendment":
            continue
        # A nested P<n+1> is a child provision, not own text.
        if len(name) == 2 and name.startswith("P") and name[1:].isdigit() and name[1:] > own_level:
            continue
        if name in {"Pnumber", "Title", "Text"}:
            text = " ".join("".join(child.itertext()).split())
            if text:
                parts.append(text)
        elif name.endswith("para"):
            parts.extend(_para_text(child))
    return "\n".join(parts)


def _para_text(para: ET.Element) -> list[str]:
    """Own prose of a ``P<n>para`` wrapper, excluding nested subsections."""
    nested = any(len(_local(g)) == 2 and _local(g).startswith("P") and _local(g)[1:].isdigit() for g in list(para))
    if not nested:
        text = " ".join("".join(para.itertext()).split())
        return [text] if text else []
    # Para mixing prose with nested subsections: keep only the direct
    # Text prose, the subsections become children.
    return [
        text
        for grand in list(para)
        if _local(grand) == "Text" and (text := " ".join("".join(grand.itertext()).split()))
    ]


def _provision_children(section: ET.Element) -> tuple[Provision, ...]:
    """Nested ``P<n+1>`` subsections of *section* as provisions."""
    own_level = _local(section)[1]
    children: list[Provision] = []
    # Descend through paras: subsections nest inside P<n>para wrappers.
    # Never descend into BlockAmendment: quoted insert text, not structure.
    stack: list[ET.Element] = [c for c in list(section) if _local(c) != "BlockAmendment"]
    while stack:
        element = stack.pop(0)
        name = _local(element)
        if len(name) == 2 and name.startswith("P") and name[1:].isdigit() and name[1:] > own_level:
            children.append(_provision(element))
        elif name != "BlockAmendment":
            stack.extend(list(element))
    return tuple(children)


def _provision(section: ET.Element) -> Provision:
    """One ``P<n>`` section element as a :class:`Provision`."""
    raw_id = section.attrib.get("id") or ""
    number: str | None = None
    for child in list(section):
        if _local(child) == "Pnumber":
            number = " ".join("".join(child.itertext()).split()) or None
            break
    eid = raw_id.replace("-", "_") if raw_id else (f"sec_{number}" if number else "sec")
    return Provision(
        id=eid,
        num=number,
        heading=None,
        text=_section_text(section),
        children=_provision_children(section),
    )


def _provisions(root: ET.Element) -> tuple[Provision, ...]:
    """Top-level provisions: the Body's ``P1``/``P1group`` sections in order."""
    for child in root:
        if _local(child) == "Metadata":
            continue
        body: ET.Element | None = None
        for grand in list(child):
            if _local(grand) == "Body":
                body = grand
                break
        if body is None:
            continue
        provisions: list[Provision] = []
        for group in list(body):
            name = _local(group)
            if name == "P1":
                provisions.append(_provision(group))
            elif name == "P1group":
                title_el = next((g for g in list(group) if _local(g) == "Title"), None)
                heading = " ".join("".join(title_el.itertext()).split()) if title_el is not None else None
                for section in [g for g in list(group) if _local(g) == "P1"]:
                    provision = _provision(section)
                    provisions.append(
                        Provision(
                            id=provision.id,
                            num=provision.num,
                            heading=heading,
                            text=provision.text,
                            children=provision.children,
                        )
                    )
        return tuple(provisions)
    return ()


class LegislationGovUkAdapter(SourceAdapter):
    """Fetch UK legislation from the official legislation.gov.uk API."""

    source_id: ClassVar[str] = "uk"
    name: ClassVar[str] = "legislation.gov.uk (The National Archives)"
    jurisdiction: ClassVar[str] = "GB"
    channel: ClassVar[str] = "legislation"
    homepage: ClassVar[str] = "https://www.legislation.gov.uk"
    license_note: ClassVar[str] = "Open Government Licence v3.0"
    crawl_delay_seconds: ClassVar[float] = 5.0
    text_format: ClassVar[str] = "xml"

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one legislation item's metadata by its URL path *law_id*.

        The ``dc:modified`` stamp is the metadata record's own
        timestamp — a re-publish moves it without any amendment — so it
        must not pose as an amendment date. ``last_amended`` therefore
        stays ``None``; ``consolidated_as_of`` carries the record's
        ``dct:valid`` point-in-time (the date the consolidation reflects
        the law). ``provisions`` parses the Body's sections (``sec_<n>``)
        with their subsections as children.
        """
        law_id = law_id.strip("/")
        url = f"{_BASE}/{law_id}/data.xml"
        body = self._get(url)
        root = parse_xml(body, f"legislation.gov.uk returned malformed XML for {law_id!r}")
        uri = root.attrib.get("DocumentURI") or url
        title = _meta_text(root, "title")
        extras = pairs(
            (
                ("legislation_type", _root_type(root)),
                ("publisher", _meta_text(root, "publisher")),
                ("provision_count", root.attrib.get("NumberOfProvisions")),
                ("valid_from", _meta_text(root, "valid")),
            )
        )
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            channel=self.channel,
            law_id=law_id,
            title=title or uri,
            url=uri,
            language=_meta_text(root, "language"),
            last_amended=None,
            consolidated_as_of=_meta_text(root, "valid"),
            text_url=url,
            akn_url=f"{_BASE}/{law_id}/data.akn",
            extras=extras,
            provisions=_provisions(root),
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
