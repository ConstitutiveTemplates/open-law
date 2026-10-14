"""United States eCFR adapter — the official electronic Code of Federal Regulations.

The eCFR JSON API (search at ``/search/v1/results``, full XML at
``/versioner/v1/full``) is the machine channel: search resolves the
deepest hierarchy node (title/part/section) and fetch pulls the dated
full-XML for that title. Query-highlight ``<strong>``/``<span>`` markup
in headings is stripped for display titles; the dated title XML already
carries the section text, so no HTML scraping is needed.
``consolidated_as_of`` pins the point-in-time date of the fetched XML
(the eCFR serves the current text), ``last_amended`` stays ``None``
because the API reports no per-node amendment date, and
``promulgation_date`` on summaries carries the search-side
``starts_on`` when the API reports one.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from typing import ClassVar
from typing import cast

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.adapter import SourceAdapter
from open_law.sources.markup import strip_markup
from open_law.sources.parsing import as_dict
from open_law.sources.parsing import as_str
from open_law.sources.parsing import clamp_limit
from open_law.sources.parsing import decode_json

__all__ = ["EcfrAdapter"]

_BASE = "https://www.ecfr.gov/api"
_HUMAN = "https://www.ecfr.gov"

_HEAD_RE = re.compile(r"<HEAD[^>]*>(.*?)</HEAD>", re.DOTALL)


def _today() -> str:
    """Point-in-time date for ``full/`` URLs and ``consolidated_as_of`` (eCFR serves the current text)."""
    return dt.datetime.now(dt.UTC).date().isoformat()


def _node_path(hierarchy: dict[str, object]) -> str:
    """Canonical law_id from a search result's hierarchy (deepest wins)."""
    title = as_str(hierarchy.get("title"))
    if title is None:
        return ""
    path = f"title-{title}"
    if section := as_str(hierarchy.get("section")):
        return f"{path}/section-{section}"
    if part := as_str(hierarchy.get("part")):
        path += f"/part-{part}"
    if subpart := as_str(hierarchy.get("subpart")):
        path += f"/subpart-{subpart}"
    return path


def _node_title(entry: dict[str, object]) -> str | None:
    """Best display title: deepest heading, else the citation-style path."""
    headings = as_dict(entry.get("headings"))
    for level in ("section", "subpart", "part", "chapter", "title"):
        if text := strip_markup(as_str(headings.get(level))):
            return text
    hierarchy_headings = as_dict(entry.get("hierarchy_headings"))
    if text := strip_markup(as_str(hierarchy_headings.get("title"))):
        return text
    return None


def _full_url(law_id: str) -> tuple[str, str | None]:
    """``title-N[/part-P|/section-S]`` → (full-XML url, node description).

    The versioner takes ``part=`` or ``section=`` query params on top of a
    dated title; deeper nodes need the parent part for correct XML scope.
    """
    segments = [seg for seg in law_id.strip("/").split("/") if seg]
    if not segments or not segments[0].startswith("title-"):
        return "", f"unrecognised eCFR node {law_id!r}; expected title-N[/part-P|/section-S]"
    title = segments[0].removeprefix("title-")
    date = _today()
    params: dict[str, str] = {}
    part = section = None
    for seg in segments[1:]:
        if seg.startswith("part-"):
            part = seg.removeprefix("part-")
        elif seg.startswith("section-"):
            section = seg.removeprefix("section-")
    if part:
        params["part"] = part
    if section:
        params["section"] = section
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return f"{_BASE}/versioner/v1/full/{date}/title-{title}.xml{query}", None


class EcfrAdapter(SourceAdapter):
    """Search and fetch US federal regulations via the eCFR public API."""

    source_id: ClassVar[str] = "us-ecfr"
    name: ClassVar[str] = "eCFR — Code of Federal Regulations (OFR/NARA)"
    jurisdiction: ClassVar[str] = "US"
    channel: ClassVar[str] = "regulations"
    homepage: ClassVar[str] = "https://www.ecfr.gov"
    license_note: ClassVar[str] = "US government work — public domain (17 USC §105)"
    crawl_delay_seconds: ClassVar[float] = 1.0
    text_format: ClassVar[str] = "xml"

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Full-text search the CFR; ``limit`` is clamped to at least 1."""
        size = clamp_limit(limit)
        url = f"{_BASE}/search/v1/results?query={urllib.parse.quote(query)}&per_page={size}"
        body = self._get(url)
        decoded = decode_json(body, f"eCFR returned malformed JSON for query {query!r}")
        payload = as_dict(decoded)
        summaries: list[LawSummary] = []
        raw_results = payload.get("results")
        results = [cast("dict[str, object]", r) for r in cast("list[object]", raw_results or []) if isinstance(r, dict)]
        for row in results:
            hierarchy = as_dict(row.get("hierarchy"))
            law_id = _node_path(hierarchy)
            title = _node_title(row)
            if not law_id or title is None:
                continue
            node_type = as_str(row.get("type")) or "?"
            starts = as_str(row.get("starts_on"))
            extras = {"node_type": node_type}
            if change_types := row.get("change_types"):
                extras["change_types"] = ",".join(str(c) for c in cast("list[object]", change_types))
            summaries.append(
                LawSummary(
                    source=self.source_id,
                    jurisdiction=self.jurisdiction,
                    channel=self.channel,
                    law_id=law_id,
                    title=title,
                    promulgation_date=starts,
                    url=f"{_HUMAN}/current/{law_id.replace('/', '/')}",
                    extras=extras,
                )
            )
        return summaries[:size]

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one CFR node's full-text XML as a :class:`Law`.

        *law_id* is an eCFR path (``title-16/part-312`` or
        ``title-16/part-312/section-312.5``). The dated ``full`` endpoint is
        pinned to today — eCFR is a point-in-time corpus, so
        ``consolidated_as_of`` is that date; ``last_amended`` stays
        ``None`` because the API reports no per-node amendment date.
        """
        url, problem = _full_url(law_id)
        if problem is not None:
            msg = problem
            raise ValueError(msg)
        body = self._get(url)
        # The XML root's <HEAD> is the node heading (e.g. "PART 312—CHILDREN'S
        # ONLINE PRIVACY PROTECTION RULE"); keep it as the title.
        head = _HEAD_RE.search(body)
        title = strip_markup(head.group(1)) if head else None
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            channel=self.channel,
            law_id=law_id,
            title=title or law_id,
            url=f"{_HUMAN}/current/{law_id.replace('/', '/')}",
            language="eng",
            last_amended=None,
            consolidated_as_of=_today(),
            text_url=url,
            extras={"format": "ecfr-xml"},
        )
