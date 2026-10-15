"""EU Publications Office (CELLAR) adapter — EU law metadata by CELEX.

CELLAR, the Publications Office's content repository, serves any CELEX
resource with HTTP content negotiation: asking for ``application/rdf+xml``
returns a compact RDF metadata graph (titles, dates, language) instead of
the full-text XHTML. No registration, and robots.txt imposes no limits
beyond the fetcher's defaults. Language negotiation is pinned to English
via ``Accept-Language``; the parsed fields report exactly that expression.

``fetch`` makes two polite requests: the RDF metadata at
``<celex>`` (the fetcher's default ``Accept``) and the English XHTML
rendition at ``<celex>.ENG.xhtml`` (per-request ``Accept:
application/xhtml+xml``), whose ``div.eli-subdivision#art_N`` articles
become the provision tree. A missing rendition (404) is not an error:
the law returns with ``provisions=()``. The cache keys each URL with the
headers it was fetched under, so the RDF and XHTML entries never collide.

Law identifiers are CELEX numbers, e.g. ``32022R2065`` (the Digital
Services Act regulation).
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import ClassVar

import httpx
from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.models import Provision
from open_law.sources.adapter import NotAvailableBySourceError
from open_law.sources.adapter import SourceAdapter
from open_law.sources.parsing import parse_xml
from open_law.sources.parsing import xml_text

__all__ = ["EurlexAdapter"]

_BASE = "https://publications.europa.eu/resource/celex"
_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_CDM = "{http://publications.europa.eu/ontology/cdm#}"
_CMR = "{http://publications.europa.eu/ontology/cdm/cmr#}"
_XHTML = "{http://www.w3.org/1999/xhtml}"
_XHTML_HEADERS = {"Accept": "application/xhtml+xml"}

# Numbered-paragraph blocks inside an article (``001.001``).
_PARA_ID_RE = re.compile(r"^[0-9]+[.][0-9]+$")
# Article 3's definition letters, table cells: ``(a)`` … ``(x)``.
_ITEM_NUM_RE = re.compile(r"^\([a-z0-9]+\)$")

# cdm properties tried in order for a usable title.
_TITLE_PROPS = ("expression_title", "title", "expression_title_short", "title_short")


def _tail(uri: str) -> str:
    """Last segment of a URI path or fragment (e.g. an authority code)."""
    return uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


@dataclass(frozen=True)
class _RdfFacts:
    """Fields the RDF scan gathered across the graph's descriptions."""

    title: str | None = None
    title_short: str | None = None
    language: str | None = None
    created: str | None = None
    last_modified: str | None = None
    resource_type: str | None = None


def _iso_day(value: str | None) -> str | None:
    """ISO-8601 day from a CELLAR datetime (``2023-12-13T10:52…``), else ``None``."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _first_text(description: ET.Element, qnames: tuple[str, ...]) -> str | None:
    """First non-empty text among fully-qualified *qnames* in *description*."""
    for qname in qnames:
        if (text := xml_text(description.find(qname))) is not None:
            return text
    return None


def _first_resource(description: ET.Element, props: tuple[str, ...]) -> str | None:
    """rdf:resource tail of the first *props* child that carries one."""
    for prop in props:
        element = description.find(f"{_CDM}{prop}")
        if element is not None:
            resource = element.attrib.get(f"{_RDF}resource")
            if resource:
                return _tail(resource)
    return None


def _rdf_type(description: ET.Element) -> str | None:
    """rdf:type resource tail of *description* (work/expression/...)."""
    element = description.find(f"{_RDF}type")
    resource = element.attrib.get(f"{_RDF}resource") if element is not None else None
    return _tail(resource) if resource else None


def _scan_descriptions(root: ET.Element) -> _RdfFacts:
    """First-found value of each tracked field across the RDF descriptions."""
    facts = _RdfFacts()
    for description in root.findall(f"{_RDF}Description"):
        facts = _RdfFacts(
            title=facts.title or _first_text(description, tuple(f"{_CDM}{prop}" for prop in _TITLE_PROPS[:2])),
            title_short=facts.title_short
            or _first_text(description, tuple(f"{_CDM}{prop}" for prop in _TITLE_PROPS[2:])),
            language=facts.language or _first_resource(description, ("expression_uses_language", "lang")),
            created=facts.created or _first_text(description, (f"{_CMR}creationDate",)),
            last_modified=facts.last_modified or _first_text(description, (f"{_CMR}lastModificationDate",)),
            resource_type=facts.resource_type or _rdf_type(description),
        )
    return facts


def _local(element: ET.Element) -> str:
    """Tag name without its namespace."""
    return element.tag.rpartition("}")[2]


def _clean(element: ET.Element) -> str:
    """Whitespace-collapsed text of *element* (non-breaking spaces included)."""
    return " ".join("".join(element.itertext()).split())


def _table_entry(table: ET.Element) -> tuple[str | None, str] | None:
    """``(num, text)`` of one two-column item table: ``("(a)", "a framework…")``."""
    cells = [_clean(td) for td in table.iter(f"{_XHTML}td")]
    if not cells:
        return None
    first, rest = cells[0], " ".join(cells[1:]).strip()
    num = first if _ITEM_NUM_RE.match(first) else None
    text = rest if num is not None else f"{first} {rest}".strip()
    return (num, text) if text else None


def _item_line(table: ET.Element) -> str | None:
    """One item table as a text line (``(a) a framework…``)."""
    entry = _table_entry(table)
    if entry is None:
        return None
    num, text = entry
    return f"{num} {text}" if num is not None else text


def _article_heading(article: ET.Element) -> str | None:
    """The article's own ``oj-sti-art`` subject, directly or in its title div."""
    for child in list(article):
        name = _local(child)
        if name == "p" and child.get("class") == "oj-sti-art" and (text := _clean(child)):
            return text
        if name == "div" and (child.get("class") or "") == "eli-title":
            for subject in child.iter(f"{_XHTML}p"):
                if subject.get("class") == "oj-sti-art" and (text := _clean(subject)):
                    return text
    return None


def _block_parts(block: ET.Element) -> tuple[list[str], list[tuple[str | None, str]]]:
    """Own prose lines and ``(num, text)`` item pairs of a paragraph *block*."""
    parts = [
        text
        for child in list(block)
        if _local(child) == "p" and child.get("class") == "oj-normal" and (text := _clean(child))
    ]
    items = [entry for table in block.iter(f"{_XHTML}table") if (entry := _table_entry(table)) is not None]
    return parts, items


def _paragraph_children(article_id: str, blocks: list[ET.Element], start: int) -> tuple[Provision, ...]:
    """Numbered-paragraph ``div`` blocks as provisions (``<art>__para_N``)."""
    children: list[Provision] = []
    for offset, block in enumerate(blocks, start=start):
        parts, items = _block_parts(block)
        suffix = (block.get("id") or "").strip().split(".")[-1].lstrip("0") or str(offset)
        para_id = f"{article_id}__para_{suffix}"
        num = suffix if suffix.isdigit() else None
        item_children = tuple(
            Provision(id=f"{para_id}__item_{index}", num=item_num, heading=None, text=item_text, children=())
            for index, (item_num, item_text) in enumerate(items, start=1)
        )
        text = "\n".join(parts)
        if not text and not item_children:
            continue
        children.append(Provision(id=para_id, num=num, heading=None, text=text, children=item_children))
    return tuple(children)


def _article_own_text(article: ET.Element) -> str:
    """Article-level prose: bare ``oj-normal`` paragraphs and item tables.

    Numbered paragraph blocks are child provisions, so they contribute
    nothing here; a list that sits directly under the article (Article
    3's definition letters) is the article's own text, not a node.
    """
    lines: list[str] = []
    for child in list(article):
        name = _local(child)
        if name == "p" and child.get("class") == "oj-normal":
            if text := _clean(child):
                lines.append(text)
        elif name == "table" and (line := _item_line(child)) is not None:
            lines.append(line)
    return "\n".join(lines)


def _article_provision(article: ET.Element, index: int) -> Provision | None:
    """One ``div.eli-subdivision#art_N`` article as a :class:`Provision`."""
    raw_id = (article.get("id") or "").strip()
    num_el = next(
        (
            child
            for child in list(article)
            if _local(child) == "p" and child.get("class") == "oj-ti-art" and _clean(child)
        ),
        None,
    )
    num = _clean(num_el) if num_el is not None else None
    heading = _article_heading(article)
    art_num = raw_id[len("art_") :] if raw_id.startswith("art_") else ""
    art_id = f"art_{art_num}" if art_num and re.fullmatch(r"[0-9A-Za-z]+", art_num) else f"art_{index}"
    paragraphs = [
        child
        for child in list(article)
        if _local(child) == "div"
        and (child.get("class") or "") != "eli-title"
        and _PARA_ID_RE.match((child.get("id") or "").strip())
    ]
    children = _paragraph_children(art_id, paragraphs, start=1)
    text = _article_own_text(article)
    if not text and not children and heading is None and num is None:
        return None
    return Provision(id=art_id, num=num, heading=heading, text=text, children=children)


def _article_provisions(root: ET.Element) -> tuple[Provision, ...]:
    """Top-level provisions of an EUR-Lex XHTML rendition in document order."""
    provisions: list[Provision] = []
    index = 0
    for element in root.iter():
        if not isinstance(element.tag, str) or _local(element) != "div":
            continue
        if (element.get("class") or "") != "eli-subdivision":
            continue
        if not (element.get("id") or "").startswith("art_"):
            continue
        index += 1
        provision = _article_provision(element, index)
        if provision is not None:
            provisions.append(provision)
    return tuple(provisions)


class EurlexAdapter(SourceAdapter):
    """Fetch EU law metadata from CELLAR by CELEX number."""

    source_id: ClassVar[str] = "eu"
    name: ClassVar[str] = "EUR-Lex / CELLAR (Publications Office)"
    jurisdiction: ClassVar[str] = "EU"
    channel: ClassVar[str] = "legislation"
    homepage: ClassVar[str] = "https://eur-lex.europa.eu"
    license_note: ClassVar[str] = "Commission Decision 2011/833/EU (reuse with attribution)"
    crawl_delay_seconds: ClassVar[float] = 1.0
    text_format: ClassVar[str] = "xml"
    http_headers: ClassVar[dict[str, str]] = {
        "Accept": "application/rdf+xml",
        "Accept-Language": "eng",
    }

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one CELEX resource's metadata and article tree as a :class:`Law`.

        CELLAR's ``lastModificationDate`` is the metadata record's own
        timestamp — a re-ingest moves it without any amendment — so it
        must not pose as an amendment date. ``last_amended`` therefore
        stays ``None`` (CELLAR's metadata graph states no per-act
        amendment date); ``consolidated_as_of`` carries the record's
        last-modification day as the as-of date of the served text.
        ``provisions`` parses the English XHTML rendition's articles
        (``art_N`` with numbered paragraphs as children); a missing
        rendition (404) leaves them empty instead of failing the fetch.
        """
        celex = law_id.strip()
        url = f"{_BASE}/{urllib.parse.quote(celex)}"
        body = self._get(url)
        root = parse_xml(body, f"CELLAR returned malformed RDF for {celex!r}")
        facts = _scan_descriptions(root)
        title = facts.title or facts.title_short or celex
        extras = {"celex": celex}
        if facts.resource_type is not None:
            extras["resource_type"] = facts.resource_type
        if facts.title_short is not None:
            extras["title_short"] = facts.title_short
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            channel=self.channel,
            law_id=celex,
            title=title,
            url=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
            language=facts.language,
            last_amended=None,
            consolidated_as_of=_iso_day(facts.last_modified),
            text_url=url,
            extras=extras,
            provisions=self._article_provisions(celex),
        )

    def _article_provisions(self, celex: str) -> tuple[Provision, ...]:
        """English XHTML rendition's articles, or ``()`` when it 404s."""
        url = f"{_BASE}/{urllib.parse.quote(celex)}.ENG.xhtml"
        try:
            body = self.fetcher.fetch_text(url, discover=False, headers=dict(_XHTML_HEADERS))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return ()
            raise
        root = parse_xml(body, f"CELLAR returned malformed XHTML for {celex!r}")
        return _article_provisions(root)

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Not offered: CELLAR discovery runs through its SPARQL endpoint.

        Full-text search lives at EUR-Lex's human search UI; machine
        discovery would go through the Publications Office SPARQL
        endpoint, which deserves its own adapter rather than a bolt-on.
        """
        msg = (
            "CELLAR offers SPARQL, not keyword search "
            f"(query={query!r}, limit={limit}); fetch by CELEX id "
            "(e.g. '32022R2065') or see the SPARQL endpoint at "
            "publications.europa.eu/webapi/rdf/sparql"
        )
        raise NotAvailableBySourceError(msg)
