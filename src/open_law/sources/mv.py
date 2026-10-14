"""Maldives adapter — statutes from mvlaw.gov.mv (Attorney General's Office).

mvlaw.gov.mv is the AGO's official legislation database: every act is a
server-rendered page at ``/dv/legislations/<id>/consolidations/<cid>``
whose full section tree arrives embedded in the page (Inertia
``data-page`` payload — ``sections`` with ``number``/``title``/``content``
and nested ``children``). robots.txt is ``User-agent: *`` /
``Disallow:`` (empty = allow all, verified 2026-10-13). The ``/api/v1/``
JSON router the bundles advertise answers 401 without a session, so the
adapter reads the server-rendered page payload instead — plain
server-rendered content, fetched politely, one page per call (the
charter's "scraping last", as with the ``bd``/``np`` adapters).

``law_id`` is the numeric legislation id (``291``); ``/dv/legislations/<id>``
redirects to the latest consolidation, so ``fetch`` follows it and
reports the consolidation as ``text_url``. ``search`` walks the
server-rendered ``/dv/legislations?page=<n>`` index (same embedded
payload, 20 rows per page) matching title and legislation number.
"""

from __future__ import annotations

import html as _html
import re
from typing import ClassVar

from typing_extensions import override

from open_law.dates import to_iso_date
from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.adapter import SourceAdapter
from open_law.sources.markup import collapse_markup
from open_law.sources.parsing import as_dict
from open_law.sources.parsing import as_dict_list
from open_law.sources.parsing import as_str
from open_law.sources.parsing import clamp_limit
from open_law.sources.parsing import decode_json
from open_law.sources.parsing import pairs

__all__ = ["MvLawAdapter"]

_BASE = "https://mvlaw.gov.mv"
_INDEX = f"{_BASE}/dv/legislations"

_ID_RE = re.compile(r"^\d+$")
_APP_DIV = '<div id="app" data-page="'


def _page_component(body: str, url: str) -> tuple[str, dict[str, object]]:
    """The (component, props) pair of the page's embedded payload."""
    # The payload is HTML-escaped JSON in a double-quoted attribute;
    # inner quotes are `&quot;`-escaped, so the first literal `"` ends it.
    start = body.find(_APP_DIV)
    if start < 0:
        msg = f"mvlaw page at {url} has no embedded law data"
        raise ValueError(msg)
    content_start = start + len(_APP_DIV)
    end = body.find('"', content_start)
    if end < 0:
        msg = f"mvlaw page at {url} has truncated law data"
        raise ValueError(msg)
    raw = _html.unescape(body[content_start:end])
    decoded = decode_json(raw, f"mvlaw page at {url} has malformed law data")
    page = as_dict(decoded)
    component = as_str(page.get("component")) or ""
    return component, as_dict(page.get("props"))


def _iso_date(value: object) -> str | None:
    """ISO-8601 date from an mvlaw ``YYYY-MM-DDTHH:MM:SS.000000Z`` timestamp."""
    text = as_str(value)
    if text is None:
        return None
    return to_iso_date(text[:10])


def _section_text(section: dict[str, object], parts: list[str]) -> None:
    """Append one section's heading + content to *parts*, depth-first."""
    number = collapse_markup(as_str(section.get("number")) or "")
    title = collapse_markup(as_str(section.get("title")) or "")
    head = " ".join(part for part in (number, title) if part)
    if head:
        parts.append(head)
    content = collapse_markup(as_str(section.get("display_text")) or as_str(section.get("content")) or "")
    if content:
        parts.append(content)
    for child in as_dict_list(section.get("children")):
        _section_text(child, parts)


def _full_text(sections: object) -> str:
    """Plain text of the consolidation's section tree, depth-first."""
    parts: list[str] = []
    for section in as_dict_list(sections):
        _section_text(section, parts)
    return "\n\n".join(parts)


def _summary(row: dict[str, object], source_id: str, jurisdiction: str) -> LawSummary:
    """One index row as a :class:`LawSummary`."""
    law_id = str(row.get("id"))
    title = as_str(row.get("title")) or law_id
    url = as_str(row.get("latest_consolidation_url")) or as_str(row.get("permalink"))
    return LawSummary(
        source=source_id,
        jurisdiction=jurisdiction,
        law_id=law_id,
        title=title,
        promulgation_date=_iso_date(row.get("published_at")),
        url=url,
        extras=pairs(
            (
                ("legislation_no", as_str(row.get("legislation_no"))),
                ("slug", as_str(row.get("slug"))),
            )
        ),
    )


class MvLawAdapter(SourceAdapter):
    """Fetch Maldivian legislation from the AGO's mvlaw database."""

    source_id: ClassVar[str] = "mv"
    name: ClassVar[str] = "mvlaw (Attorney General's Office, Maldives)"
    jurisdiction: ClassVar[str] = "MV"
    homepage: ClassVar[str] = "https://mvlaw.gov.mv"
    license_note: ClassVar[str] = "Government of Maldives publication (no explicit reuse licence)"
    crawl_delay_seconds: ClassVar[float] = 2.0
    text_format: ClassVar[str] = "html"

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Title/legislation-number search over the legislations index.

        The index is server-rendered (20 rows per embedded-payload
        page); the adapter walks pages in order, matching the query
        against the title and legislation number case-insensitively.
        """
        size = clamp_limit(limit)
        needle = query.strip().lower()
        if not needle:
            return []
        summaries: list[LawSummary] = []
        page = 1
        while len(summaries) < size:
            body = self._get(f"{_INDEX}?page={page}")
            _component, props = _page_component(body, f"{_INDEX}?page={page}")
            index = as_dict(props.get("legislations"))
            rows = as_dict_list(index.get("data"))
            if not rows:
                break
            for row in rows:
                title = as_str(row.get("title")) or ""
                number = as_str(row.get("legislation_no")) or ""
                if needle not in f"{title.lower()} {number.lower()}":
                    continue
                summaries.append(_summary(row, self.source_id, self.jurisdiction))
                if len(summaries) >= size:
                    break
            last_page = index.get("last_page")
            last = int(last_page) if isinstance(last_page, int) else page
            if page >= max(last, 1):
                break
            page += 1
        return summaries

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one legislation's latest consolidation by numeric id.

        *law_id* is the legislation id (``291``); the show route
        redirects to the latest ``/consolidations/<cid>`` page, whose
        embedded section tree is the full text. ``text_url`` is the
        consolidation page; ``url`` is the human show route.
        """
        lid = law_id.strip()
        if not _ID_RE.match(lid):
            msg = f"{law_id!r} is not an mvlaw legislation id (expected e.g. '291')"
            raise ValueError(msg)
        show_url = f"{_INDEX}/{lid}"
        body = self._get(show_url)
        component, props = _page_component(body, show_url)
        if component != "SingleConsolidation":
            msg = f"no legislation with id {lid!r} on mvlaw.gov.mv"
            raise LookupError(msg)
        legislation = as_dict(props.get("legislation"))
        title = as_str(legislation.get("content_title")) or as_str(legislation.get("title")) or lid
        number = as_str(legislation.get("legislation_no")) or as_str(props.get("legislation_number"))
        consolidation_id = as_str(props.get("consolidation_id"))
        text_url = f"{_INDEX}/{lid}/consolidations/{consolidation_id}" if consolidation_id is not None else show_url
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=lid,
            title=title,
            promulgation_date=_iso_date(legislation.get("published_at")),
            url=show_url,
            language="div",
            text_url=text_url,
            extras=pairs(
                (
                    ("legislation_no", number),
                    ("consolidation_id", consolidation_id),
                    ("slug", as_str(legislation.get("slug"))),
                    ("institution", as_str(props.get("related_institution"))),
                    ("original_document_url", as_str(props.get("original_document_url"))),
                )
            ),
        )

    @override
    def full_text(self, law_id: str) -> str:
        """The consolidation's section text, refetched from ``text_url``."""
        law = self.fetch(law_id)
        if law.text_url is None:
            return ""
        body = self._get(law.text_url)
        _component, props = _page_component(body, law.text_url)
        return _full_text(props.get("sections"))
