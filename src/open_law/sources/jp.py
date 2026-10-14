"""e-Gov 法令 adapter — Japan's official law portal API.

The Digital Agency's versioned API is the machine channel: v2 ``/laws``
for title search (JSON with ``law_info`` + ``revision_info``), v1
``/lawdata/<id>`` for the complete Law XML (title from ``LawBody /
LawTitle``, promulgation date from the ``Law`` era attributes). Unknown
ids answer ``Result/Code=1`` with an empty ``LawFullText`` — a
``ValueError``. The five Japanese eras (Meiji→Reiwa) map to Gregorian
years for ``promulgation_date``; kana title, category and law number
ride along in ``extras``.

Version-mix note (OL-16): search runs against the v2 API, but the body
text still comes from the v1 ``lawdata`` endpoint — v1 returns the
current consolidation with no revision history, so a single fetch
cannot say *when* it was last amended. Amendment awareness therefore
comes from the v2 ``revision_info`` shape alone: ``fetch`` re-queries
v2 ``/laws?law_id=<id>`` for the law's ``amendment_promulgate_date``
(``last_amended``) and ``amendment_enforcement_date``
(``consolidated_as_of``). When v2 carries no amendment dates — a fresh
enactment never amended — ``last_amended`` stays ``None``.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import ClassVar

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.models import Provision
from open_law.sources.adapter import SourceAdapter
from open_law.sources.parsing import as_dict_list
from open_law.sources.parsing import as_dict_or_none
from open_law.sources.parsing import as_str
from open_law.sources.parsing import clamp_limit
from open_law.sources.parsing import decode_json
from open_law.sources.parsing import pairs
from open_law.sources.parsing import parse_xml

__all__ = ["EgovAdapter"]

_BASE = "https://laws.e-gov.go.jp/api/2"
_V1 = "https://laws.e-gov.go.jp/api/1"
_ID_RE = re.compile(r"^[0-9A-Z]{10,}$")

_ERA_BASE: dict[str, int] = {"Meiji": 1868, "Taisho": 1912, "Showa": 1926, "Heisei": 1989, "Reiwa": 2019}


def _iso_day(value: str | None) -> str | None:
    """ISO-8601 day (``YYYY-MM-DD``) from a v2 datetime/date string, else ``None``."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _revision_dates(law_id: str, fetch_json: Callable[[str], str]) -> tuple[str | None, str | None]:
    """``(last_amended, consolidated_as_of)`` from the v2 ``revision_info`` for *law_id*.

    *fetch_json* is the adapter's bound ``_get``. The lookup is
    best-effort enrichment: any problem (no v2 record, transport
    failure, malformed JSON) yields ``(None, None)`` — an unknown
    amendment date is ``None``, never a fetch date.
    """
    try:
        body = fetch_json(f"{_BASE}/laws?law_id={urllib.parse.quote(law_id)}&limit=1")
        decoded = decode_json(body, f"e-Gov returned malformed JSON for law {law_id!r}")
    except Exception:  # noqa: BLE001
        return None, None
    payload = as_dict_or_none(decoded)
    entries = as_dict_list(payload.get("laws")) if payload is not None else []
    if not entries:
        return None, None
    revision = as_dict_or_none(entries[0].get("revision_info")) or {}
    return _iso_day(as_str(revision.get("amendment_promulgate_date"))), _iso_day(
        as_str(revision.get("amendment_enforcement_date"))
    )


def _promulgation_date(law: ET.Element) -> str | None:
    """ISO date from the ``Law`` era attributes (Meiji 29-04-27 → 1896-04-27)."""
    era = law.get("Era")
    try:
        year = int(str(law.get("Year")))
        month = int(str(law.get("PromulgateMonth")))
        day = int(str(law.get("PromulgateDay")))
    except (TypeError, ValueError):
        return None
    if era is None or era not in _ERA_BASE:
        return None
    return f"{_ERA_BASE[era] + year - 1:04d}-{month:02d}-{day:02d}"


class EgovAdapter(SourceAdapter):
    """Search Japan's e-Gov law list; fetch full text via the v1 lawdata endpoint."""

    source_id: ClassVar[str] = "jp"
    name: ClassVar[str] = "e-Gov 法令検索 (Digital Agency)"
    jurisdiction: ClassVar[str] = "JP"
    channel: ClassVar[str] = "legislation"
    homepage: ClassVar[str] = "https://laws.e-gov.go.jp"
    license_note: ClassVar[str] = "政府標準利用規約 (GoJ Standard Terms of Use)"
    crawl_delay_seconds: ClassVar[float] = 1.0
    text_format: ClassVar[str] = "xml"

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Title-search the law list; ``limit`` is clamped to at least 1."""
        size = clamp_limit(limit)
        url = f"{_BASE}/laws?law_title={urllib.parse.quote(query)}&limit={size}"
        body = self._get(url)
        decoded = decode_json(body, f"e-Gov returned malformed JSON for query {query!r}")
        payload = as_dict_or_none(decoded)
        if payload is None:
            msg = f"e-Gov returned a non-object JSON body for query {query!r}"
            raise ValueError(msg)
        summaries: list[LawSummary] = []
        for entry in as_dict_list(payload.get("laws")):
            info = as_dict_or_none(entry.get("law_info")) or {}
            revision = as_dict_or_none(entry.get("revision_info")) or {}
            law_id = as_str(info.get("law_id"))
            title = as_str(revision.get("law_title")) or as_str(info.get("law_num"))
            if law_id is None or title is None:
                continue
            summaries.append(
                LawSummary(
                    source=self.source_id,
                    jurisdiction=self.jurisdiction,
                    channel=self.channel,
                    law_id=law_id,
                    title=title,
                    promulgation_date=as_str(info.get("promulgation_date")),
                    url=f"https://laws.e-gov.go.jp/document?law_id={urllib.parse.quote(law_id)}",
                    extras=pairs(
                        (
                            ("law_num", info.get("law_num")),
                            ("law_title_kana", revision.get("law_title_kana")),
                            ("category", revision.get("category")),
                        )
                    ),
                )
            )
        return summaries

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one law's full-text XML as a :class:`Law` (no key needed).

        *law_id* is the e-Gov id (``325AC0000000041``). The v1 ``lawdata``
        endpoint returns the complete Law XML: title from ``LawBody /
        LawTitle``, promulgation date from the ``Law`` attributes, and the
        ``lawdata`` URL itself as ``text_url`` so :meth:`full_text`
        extracts the articles as plain text. Amendment dates come from a
        second, v2 ``/laws?law_id=`` lookup (see the module note): the v1
        body is a consolidation with no revision history of its own.
        Unknown ids answer ``Result/Code=1`` with an empty
        ``LawFullText`` — a ``ValueError``.
        """
        lid = law_id.strip()
        if not _ID_RE.match(lid):
            msg = f"Unrecognised e-Gov law id {law_id!r} (expected e.g. '325AC0000000041')"
            raise ValueError(msg)
        url = f"{_V1}/lawdata/{urllib.parse.quote(lid)}"
        body = self._get(url)
        root = parse_xml(body, f"e-Gov returned malformed XML for law {lid!r}")
        code = root.findtext("Result/Code")
        law = root.find("ApplData/LawFullText/Law")
        if code != "0" or law is None:
            msg = f"e-Gov has no law {lid!r} (Result/Code={code})"
            raise ValueError(msg)
        title = law.findtext("LawBody/LawTitle")
        num = law.findtext("LawBody/LawNum") or law.findtext("LawNum")
        prom = _promulgation_date(law)
        amend_prom, consolidated_as_of = _revision_dates(lid, self._get)
        # v2 stamps the enactment's own date as its "amendment" when a law
        # was never amended — that is not an amendment, so only a date
        # *later than* (i.e. different from) promulgation counts.
        last_amended = amend_prom if amend_prom is not None and amend_prom != prom else None
        extras = pairs((("law_num", num), ("era", law.get("Era")), ("law_type", law.get("LawType"))))
        extras["format"] = "egov-law-xml"
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            channel=self.channel,
            law_id=lid,
            title=(title or "").strip() or lid,
            promulgation_date=prom,
            url=f"https://laws.e-gov.go.jp/document?law_id={urllib.parse.quote(lid)}",
            language="jpn",
            last_amended=last_amended,
            consolidated_as_of=consolidated_as_of,
            text_url=url,
            extras=extras,
            provisions=_provisions(law),
        )


def _node_text(element: ET.Element) -> str:
    """Own text of *element*: sentence/number children, not nested articles."""
    parts: list[str] = []
    for child in list(element):
        tag = child.tag
        if tag in {"Article", "Paragraph", "Item", "Subitem", "List"}:
            continue
        text = "".join(child.itertext()).strip()
        if text:
            parts.append(" ".join(text.split()))
    return "\n".join(parts)


def _article_id(article: ET.Element) -> str:
    """Akoma Ntoso eId of one ``Article`` element (``art_<num>``, else ``art``)."""
    num = (article.get("Num") or "").strip()
    return f"art_{num}" if num and re.fullmatch(r"[0-9]+", num) else "art"


def _paragraph_provisions(article: ET.Element, article_id: str) -> tuple[Provision, ...]:
    """``Paragraph`` children of *article* as provisions (``<art>__para_M``)."""
    children: list[Provision] = []
    for para in article.findall("Paragraph"):
        num = (para.get("Num") or "").strip() or None
        stub = f"para_{num}" if num and re.fullmatch(r"[0-9]+", num) else "para"
        para_id = f"{article_id}__{stub}"
        items = tuple(
            Provision(
                id=f"{para_id}__item_{index}",
                num=f"({index})",
                heading=None,
                text=" ".join("".join(item.itertext()).split()),
                children=(),
            )
            for index, item in enumerate([c for c in list(para) if c.tag == "Item"], start=1)
            if "".join(item.itertext()).strip()
        )
        text_bits = [
            " ".join("".join(child.itertext()).split())
            for child in list(para)
            if child.tag in {"ParagraphNum", "ParagraphSentence"} and "".join(child.itertext()).strip()
        ]
        text = "\n".join(text_bits)
        if not text and not items:
            continue
        children.append(
            Provision(
                id=para_id,
                num=num,
                heading=None,
                text=text,
                children=items,
            )
        )
    return tuple(children)


def _provisions(law: ET.Element) -> tuple[Provision, ...]:
    """Top-level provisions of a v1 Law: MainProvision articles then SupplProvision ones.

    Article ids follow the Akoma Ntoso eId convention (``art_1``);
    supplementary articles are prefixed (``suppl_art_1``) so ids stay
    unique across the two blocks.
    """
    provisions: list[Provision] = []
    body = law.find("LawBody")
    if body is None:
        return ()
    for block, prefix in ((body.find("MainProvision"), ""), (body.find("SupplProvision"), "suppl_")):
        if block is None:
            continue
        for article in block.findall("Article"):
            base = _article_id(article)
            eid = f"{prefix}{base}"
            title = (article.findtext("ArticleTitle") or "").strip() or None
            caption = (article.findtext("ArticleCaption") or "").strip() or None
            heading = title or caption
            children = _paragraph_provisions(article, eid)
            text = _node_text(article)
            if not text and not children and heading is None:
                continue
            provisions.append(
                Provision(
                    id=eid,
                    num=title,
                    heading=caption,
                    text=text,
                    children=children,
                )
            )
    return tuple(provisions)
