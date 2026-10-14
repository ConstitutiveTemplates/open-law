"""e-Gov 法令 adapter — Japan's official law portal API.

The Digital Agency's versioned API is the machine channel: v2 ``/laws``
for title search (JSON with ``law_info`` + ``revision_info``), v1
``/lawdata/<id>`` for the complete Law XML (title from ``LawBody /
LawTitle``, promulgation date from the ``Law`` era attributes). Unknown
ids answer ``Result/Code=1`` with an empty ``LawFullText`` — a
``ValueError``. The five Japanese eras (Meiji→Reiwa) map to Gregorian
years for ``promulgation_date``; kana title, category and law number
ride along in ``extras``.
"""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import ClassVar

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
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
        extracts the articles as plain text. Unknown ids answer
        ``Result/Code=1`` with an empty ``LawFullText`` — a ``ValueError``.
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
        extras = pairs((("law_num", num), ("era", law.get("Era")), ("law_type", law.get("LawType"))))
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=lid,
            title=(title or "").strip() or lid,
            promulgation_date=prom,
            url=f"https://laws.e-gov.go.jp/document?law_id={urllib.parse.quote(lid)}",
            language="jpn",
            modified=prom,
            text_url=url,
            extras=(("format", "egov-law-xml"), *extras),
        )
