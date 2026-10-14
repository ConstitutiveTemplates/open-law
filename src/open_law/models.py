"""Unified data model for legislation fetched from source adapters.

Every source adapter (see :mod:`open_law.sources`) parses its native
format — UK ``data.xml``, Japanese e-Gov XML, EU CELLAR RDF — into these
shared classes, so callers (CLI, notebooks, future exports) never see a
source's wire format. ``LawSummary`` is the cheap list/search shape;
``Law`` adds the full-text, versioning and structure fields of one
fetched document; ``Provision`` is one node of a law's article tree.

Dates stay ISO-8601 strings exactly as the source reports them: parsing
them into ``datetime.date`` would silently invent timezone and precision
semantics the source never claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

__all__ = ["CHANNELS", "Law", "LawSummary", "Provision"]

#: What a source's publication channel carries, independent of where:
#:
#: - ``legislation``: a jurisdiction's official legislation database —
#:   primary and secondary law, in the original language.
#: - ``statutes``: primary legislation (Acts) only.
#: - ``regulations``: secondary legislation only (e.g. the eCFR).
#: - ``gazette``: the official gazette — texts as published, never
#:   consolidated.
#: - ``translation``: an official translation of another channel's
#:   texts (e.g. JLT's English versions of Japanese law).
CHANNELS: frozenset[str] = frozenset({"legislation", "statutes", "regulations", "gazette", "translation"})


@dataclass(frozen=True)
class Provision:
    """One node of a law's structure: an article, section, paragraph, ...

    - ``id``: the node's Akoma Ntoso ``eId`` — element abbreviation plus
      number (``art_23``, ``sec_1``, ``chp_2``), ancestors joined with
      ``__`` (``chp_2__art_23__para_1``), so a citation such as
      "Art. 23(1)" resolves to one id mechanically.
    - ``num``: the number as printed (``"Article 23"``, ``"第二十三条"``,
      ``"1"``), or ``None`` for unnumbered nodes.
    - ``heading``: the node's caption/title, or ``None``.
    - ``text``: the node's own text, excluding its children's.
    - ``children``: nested provisions in document order.
    """

    id: str
    num: str | None
    heading: str | None
    text: str
    children: tuple[Provision, ...] = ()


@dataclass(frozen=True)
class LawSummary:
    """One law as listed by a source: identity and title, no full text.

    - ``source``: the adapter's ``source_id`` (``"uk"``, ``"jp"``,
      ``"us-ecfr"``) — one publication channel, not a jurisdiction.
    - ``jurisdiction``: ISO 3166-1 alpha-2 code (``"US-TX"`` style
      ISO 3166-2 for subdivisions), or ``"EU"`` for union law.
    - ``channel``: what the source publishes, one of :data:`CHANNELS`.
    - ``law_id``: the source-native identifier to pass back to
      :meth:`open_law.sources.adapter.SourceAdapter.fetch`
      (``"ukcm/2023/1"``, an e-Gov ``law_id``, a CELEX number).
    - ``promulgation_date``: ISO-8601 date the law was originally
      promulgated/enacted, or ``None`` when the source does not state one.
    - ``url``: the human-readable landing page, or ``None``.
    - ``extras``: source-specific fields worth keeping but not worth
      modelling globally (publisher, provision counts, kana titles).
      Excluded from hashing so the frozen dataclass stays hashable.
    """

    source: str
    jurisdiction: str
    channel: str
    law_id: str
    title: str
    promulgation_date: str | None = None
    url: str | None = None
    extras: dict[str, str] = field(default_factory=dict[str, str], hash=False)


@dataclass(frozen=True)
class Law(LawSummary):
    """One fetched law: full-text locations, version dates, structure.

    - ``last_amended``: ISO-8601 date of the most recent amendment the
      source reports for this law, or ``None`` when the source does not
      say (never a fetch/run date, never a metadata-record timestamp).
      Comparing two fetches' ``last_amended`` is how amendments are
      detected.
    - ``consolidated_as_of``: ISO-8601 point-in-time of the served text
      — the date the consolidated version reflects the law — or ``None``
      for as-published texts and sources that do not state it.
    - ``text_url``: machine-readable full text (XML / JSON / RDF), the
      URL the adapter itself parsed.
    - ``akn_url``: an Akoma Ntoso rendition, when the source offers one —
      the interoperable format the open-law ecosystem converges on.
    - ``provisions``: the law's article tree (top-level nodes), empty
      for sources whose adapter does not parse structure.
    """

    language: str | None = None
    last_amended: str | None = None
    consolidated_as_of: str | None = None
    text_url: str | None = None
    akn_url: str | None = None
    provisions: tuple[Provision, ...] = ()
