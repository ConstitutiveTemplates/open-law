"""EU Publications Office (CELLAR) adapter — EU law metadata by CELEX.

CELLAR, the Publications Office's content repository, serves any CELEX
resource with HTTP content negotiation: asking for ``application/rdf+xml``
returns a compact RDF metadata graph (titles, dates, language) instead of
the full-text XHTML. No registration, and robots.txt imposes no limits
beyond the fetcher's defaults. Language negotiation is pinned to English
via ``Accept-Language``; the parsed fields report exactly that expression.

Law identifiers are CELEX numbers, e.g. ``32022R2065`` (the Digital
Services Act regulation).
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import ClassVar

from defusedxml.ElementTree import fromstring
from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.base import SourceAdapter

__all__ = ["EurlexAdapter"]

_BASE = "https://publications.europa.eu/resource/celex"
_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_CDM = "{http://publications.europa.eu/ontology/cdm#}"
_CMR = "{http://publications.europa.eu/ontology/cdm/cmr#}"

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
    modified: str | None = None
    resource_type: str | None = None


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
            modified=facts.modified or _first_text(description, (f"{_CMR}lastModificationDate",)),
            resource_type=facts.resource_type or _rdf_type(description),
        )
    return facts


class EurlexAdapter(SourceAdapter):
    """Fetch EU law metadata from CELLAR by CELEX number."""

    source_id: ClassVar[str] = "eu"
    name: ClassVar[str] = "EUR-Lex / CELLAR (Publications Office)"
    jurisdiction: ClassVar[str] = "EU"
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
        """Fetch one CELEX resource's RDF metadata as a :class:`Law`."""
        celex = law_id.strip()
        url = f"{_BASE}/{urllib.parse.quote(celex)}"
        body = self._get(url)
        try:
            root = fromstring(body)
        except ET.ParseError as exc:
            msg = f"CELLAR returned malformed RDF for {celex!r}"
            raise ValueError(msg) from exc
        facts = _scan_descriptions(root)
        title = facts.title or facts.title_short or celex
        extras = [("celex", celex)]
        if facts.resource_type is not None:
            extras.append(("resource_type", facts.resource_type))
        if facts.title_short is not None:
            extras.append(("title_short", facts.title_short))
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=celex,
            title=title,
            url=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
            language=facts.language,
            modified=facts.modified or facts.created,
            text_url=url,
            extras=tuple(extras),
        )

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


def _first_text(description: ET.Element, qnames: tuple[str, ...]) -> str | None:
    """First non-empty text among fully-qualified *qnames* in *description*."""
    for qname in qnames:
        element = description.find(qname)
        if element is not None and element.text and element.text.strip():
            return element.text.strip()
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
