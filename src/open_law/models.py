"""Unified data model for legislation fetched from source adapters.

Every source adapter (see :mod:`open_law.sources`) parses its native
format — UK ``data.xml``, Japanese e-Gov JSON, EU CELLAR RDF — into these
shared classes, so callers (CLI, notebooks, future exports) never see a
source's wire format. ``LawSummary`` is the cheap list/search shape;
``Law`` adds the full-text and provenance fields of one fetched document.

Dates stay ISO-8601 strings exactly as the source reports them: parsing
them into ``datetime.date`` would silently invent timezone and precision
semantics the source never claimed.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Law", "LawSummary"]


@dataclass(frozen=True)
class LawSummary:
    """One law as listed by a source: identity and title, no full text.

    - ``source``: the adapter's ``source_id`` (``"uk"``, ``"jp"``, ``"eu"``).
    - ``jurisdiction``: ISO 3166-1 alpha-2 code, or ``"EU"`` for union law.
    - ``law_id``: the source-native identifier to pass back to
      :meth:`open_law.sources.SourceAdapter.fetch` (``"ukcm/2023/1"``,
      an e-Gov ``law_id``, a CELEX number).
    - ``promulgation_date``: ISO-8601 date string as reported by the
      source, or ``None`` when the source does not state one.
    - ``url``: the human-readable landing page, or ``None``.
    - ``extras``: source-specific fields worth keeping but not worth
      modelling globally (publisher, provision counts, kana titles),
      as ``(key, value)`` pairs so the frozen dataclass stays hashable.
    """

    source: str
    jurisdiction: str
    law_id: str
    title: str
    promulgation_date: str | None = None
    url: str | None = None
    extras: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Law(LawSummary):
    """One fetched law: full-text locations plus provenance metadata.

    - ``text_url``: machine-readable full text (XML / JSON / RDF), the
      URL the adapter itself parsed.
    - ``akn_url``: an Akoma Ntoso rendition, when the source offers one —
      the interoperable format the open-law ecosystem converges on.
    """

    language: str | None = None
    modified: str | None = None
    text_url: str | None = None
    akn_url: str | None = None
