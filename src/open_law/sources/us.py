"""United States eCFR adapter — the official electronic Code of Federal Regulations.

The CFR is where most US federal *regulatory* law lives as machine-readable
text: FTC rules (COPPA, Safeguards), FDA regulations, export controls, and
agency rules that carry the force of law. For a compliance corpus it is the
highest-yield US channel — statutes (US Code) sit on a separate, bot-gated
channel (uscode.house.gov) and the govinfo API requires a registered key.

Channel: ``https://www.ecfr.gov/api/`` — key-free, robots-permitted
(``Disallow: /search`` applies to the human UI only; the ``/api/`` tree is
explicitly open), JSON for metadata and structured XML for full text.
Search and per-node full text both work without registration (verified
2026-10). The full-text endpoint requires response compression — the
fetcher's client already negotiates gzip.

Law identifiers are eCFR paths: ``title-N/part-P/section-S`` (any suffix
may be dropped to widen the node: ``title-16/part-312`` is the COPPA Rule,
``title-16`` is all of Title 16). ``fetch`` always reads the point-in-time
snapshot for *today*; historical editions are addressable by date but out
of scope for the v1 adapter.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse
from typing import ClassVar
from typing import cast

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import SourceAdapter

__all__ = ["EcfrAdapter"]

_BASE = "https://www.ecfr.gov/api"
_HUMAN = "https://www.ecfr.gov"

_TAG_RE = re.compile(r"<[^>]+>")
_HEAD_RE = re.compile(r"<HEAD[^>]*>(.*?)</HEAD>", re.DOTALL)


def _today() -> str:
    """Point-in-time date for ``full/`` URLs (eCFR serves the current text)."""
    return dt.datetime.now(dt.UTC).date().isoformat()


def _as_dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _strip_html(text: str | None) -> str | None:
    """Drop ``<strong>``/``<span>`` query-highlight markup from headings."""
    if text is None:
        return None
    clean = _TAG_RE.sub("", text).strip()
    return clean or None


def _node_path(hierarchy: dict[str, object]) -> str:
    """Canonical law_id from a search result's hierarchy (deepest wins)."""
    title = _as_str(hierarchy.get("title"))
    if title is None:
        return ""
    path = f"title-{title}"
    if section := _as_str(hierarchy.get("section")):
        return f"{path}/section-{section}"
    if part := _as_str(hierarchy.get("part")):
        path += f"/part-{part}"
    if subpart := _as_str(hierarchy.get("subpart")):
        path += f"/subpart-{subpart}"
    return path


def _node_title(entry: dict[str, object]) -> str | None:
    """Best display title: deepest heading, else the citation-style path."""
    headings = _as_dict(entry.get("headings"))
    for level in ("section", "subpart", "part", "chapter", "title"):
        if text := _strip_html(_as_str(headings.get(level))):
            return text
    hierarchy_headings = _as_dict(entry.get("hierarchy_headings"))
    if text := _strip_html(_as_str(hierarchy_headings.get("title"))):
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

    source_id: ClassVar[str] = "us"
    name: ClassVar[str] = "eCFR — Code of Federal Regulations (OFR/NARA)"
    jurisdiction: ClassVar[str] = "US"
    homepage: ClassVar[str] = "https://www.ecfr.gov"
    license_note: ClassVar[str] = "US government work — public domain (17 USC §105)"
    crawl_delay_seconds: ClassVar[float] = 1.0
    text_format: ClassVar[str] = "xml"

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Full-text search the CFR; ``limit`` is clamped to at least 1."""
        size = max(1, limit)
        url = f"{_BASE}/search/v1/results?query={urllib.parse.quote(query)}&per_page={size}"
        body = self._get(url)
        try:
            decoded = cast("object", json.loads(body))
        except json.JSONDecodeError as exc:
            msg = f"eCFR returned malformed JSON for query {query!r}"
            raise ValueError(msg) from exc
        payload = _as_dict(decoded)
        summaries: list[LawSummary] = []
        raw_results = payload.get("results")
        results = [cast("dict[str, object]", r) for r in cast("list[object]", raw_results or []) if isinstance(r, dict)]
        for row in results:
            hierarchy = _as_dict(row.get("hierarchy"))
            law_id = _node_path(hierarchy)
            title = _node_title(row)
            if not law_id or title is None:
                continue
            node_type = _as_str(row.get("type")) or "?"
            starts = _as_str(row.get("starts_on"))
            extras: list[tuple[str, str]] = [("node_type", node_type)]
            if change_types := row.get("change_types"):
                extras.append(("change_types", ",".join(str(c) for c in cast("list[object]", change_types))))
            summaries.append(
                LawSummary(
                    source=self.source_id,
                    jurisdiction=self.jurisdiction,
                    law_id=law_id,
                    title=title,
                    promulgation_date=starts,
                    url=f"{_HUMAN}/current/{law_id.replace('/', '/')}",
                    extras=tuple(extras),
                )
            )
        return summaries[:size]

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one CFR node's full-text XML as a :class:`Law`.

        *law_id* is an eCFR path (``title-16/part-312`` or
        ``title-16/part-312/section-312.5``). The dated ``full`` endpoint is
        pinned to today — eCFR is a point-in-time corpus, and ``modified``
        in the summary carries the search-side ``starts_on`` when known.
        """
        url, problem = _full_url(law_id)
        if problem is not None:
            msg = problem
            raise ValueError(msg)
        body = self._get(url)
        # The XML root's <HEAD> is the node heading (e.g. "PART 312—CHILDREN'S
        # ONLINE PRIVACY PROTECTION RULE"); keep it as the title.
        head = _HEAD_RE.search(body)
        title = _strip_html(head.group(1)) if head else None
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=law_id,
            title=title or law_id,
            url=f"{_HUMAN}/current/{law_id.replace('/', '/')}",
            language="eng",
            modified=_today(),
            text_url=url,
            extras=(("format", "ecfr-xml"),),
        )
