"""e-Gov 法令 v2 adapter — Japan's official law portal API (法令API v2).

Digital Agency's v2 API at ``laws.e-gov.go.jp/api/2`` returns JSON and,
unlike the retired v1, the law-list endpoint works without registration
(verified 2026-09). The single-law full-text endpoint, however, is
registration-gated, so :meth:`EgovAdapter.fetch` explains the
registration step instead of pretending the data is reachable.

Law identifiers are the source's ``law_id`` (e.g. ``105DF0000000337``),
which also forms the human landing page URL.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import ClassVar
from typing import cast

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.base import SourceAdapter

__all__ = ["EgovAdapter"]

_BASE = "https://laws.e-gov.go.jp/api/2"


def _as_dict(value: object) -> dict[str, object] | None:
    """*value* as a dict when it is one, else None (defensive JSON)."""
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def _as_dict_list(value: object) -> list[dict[str, object]]:
    """*value* as a list of dicts, dropping non-dict entries."""
    if not isinstance(value, list):
        return []
    return [cast("dict[str, object]", entry) for entry in cast("list[object]", value) if isinstance(entry, dict)]


def _as_str(value: object) -> str | None:
    """Non-empty *value* stringified, else None (JSON nulls and gaps)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pairs(candidates: tuple[tuple[str, object], ...]) -> tuple[tuple[str, str], ...]:
    """(key, value) pairs for the non-None *candidates*, stringified."""
    pairs: list[tuple[str, str]] = []
    for key, value in candidates:
        text = _as_str(value)
        if text is not None:
            pairs.append((key, text))
    return tuple(pairs)


class EgovAdapter(SourceAdapter):
    """Search Japan's e-Gov 法令 v2 law list (no registration needed)."""

    source_id: ClassVar[str] = "jp"
    name: ClassVar[str] = "e-Gov 法令検索 (Digital Agency)"
    jurisdiction: ClassVar[str] = "JP"
    homepage: ClassVar[str] = "https://laws.e-gov.go.jp"
    license_note: ClassVar[str] = "政府標準利用規約 (GoJ Standard Terms of Use)"

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Title-search the law list; ``limit`` is clamped to at least 1."""
        size = max(1, limit)
        url = f"{_BASE}/laws?law_title={urllib.parse.quote(query)}&limit={size}"
        body = self._get(url)
        try:
            decoded = cast("object", json.loads(body))
        except json.JSONDecodeError as exc:
            msg = f"e-Gov returned malformed JSON for query {query!r}"
            raise ValueError(msg) from exc
        payload = _as_dict(decoded)
        if payload is None:
            msg = f"e-Gov returned a non-object JSON body for query {query!r}"
            raise ValueError(msg)
        summaries: list[LawSummary] = []
        for entry in _as_dict_list(payload.get("laws")):
            info = _as_dict(entry.get("law_info")) or {}
            revision = _as_dict(entry.get("revision_info")) or {}
            law_id = _as_str(info.get("law_id"))
            title = _as_str(revision.get("law_title")) or _as_str(info.get("law_num"))
            if law_id is None or title is None:
                continue
            summaries.append(
                LawSummary(
                    source=self.source_id,
                    jurisdiction=self.jurisdiction,
                    law_id=law_id,
                    title=title,
                    promulgation_date=_as_str(info.get("promulgation_date")),
                    url=f"https://laws.e-gov.go.jp/document?law_id={urllib.parse.quote(law_id)}",
                    extras=_pairs(
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
        """Not offered without registration: the full-text API needs a key.

        The v2 law-list endpoint used by :meth:`search` is open, but
        per-law full text (``/api/2/laws/...`` document endpoints)
        requires the operator to register an application at the e-Gov
        法令API site first.
        """
        msg = (
            f"e-Gov full text for {law_id!r} requires 法令API 利用者登録 "
            "(application key); register at https://elsur.e-gov.go.jp/ "
            "then extend this adapter — the landing page is "
            f"https://laws.e-gov.go.jp/document?law_id={urllib.parse.quote(law_id)}"
        )
        raise NotAvailableBySourceError(msg)
