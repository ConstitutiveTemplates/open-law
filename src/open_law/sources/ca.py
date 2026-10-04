"""Canada adapter — consolidated federal statutes from the Justice Laws Website.

Consolidated Acts of Parliament live at ``laws-lois.justice.gc.ca`` as dated
XML snapshots: ``/eng/XML/<CODE>.xml`` serves the full bilingual consolidation
(point-in-time ``pit-date``, section count, in-force status). The human act
page is ``/eng/acts/<CODE>/`` (``.../FullText.html`` for the single-page HTML).
A short code like ``C-46`` is the Criminal Code, ``P-8.6`` is PIPEDA, ``A-1``
is the Access to Information Act.

Keyword search lives at a legacy ``Search/Search.aspx`` form with no machine
endpoint (probing returns the empty search page, not results), so ``search``
follows the eur-lex precedent: raise :class:`NotAvailableBySourceError` with
the actionable next step — fetch by act code. The acts index at
``/eng/acts/`` (per-act ``/eng/acts/<CODE>/`` pages) is the human discovery
surface; title-to-code mapping is a lookup, not a full-text search worth
pretending.

Channel notes (verified 2026-10-04): no robots.txt (404 — no Crawl-delay to
mirror, ``crawl_delay_seconds`` stays conservative at 2.0); per-act XML is
small except the Criminal Code (~5.8 MB, budget-aware fetchers still fine);
consolidations are Crown copyright with a standing non-commercial
reproduction permission.
"""

import datetime as dt
import re
from typing import ClassVar

from typing_extensions import override

from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.base import SourceAdapter

__all__ = ["JusticeLawsAdapter"]

_BASE = "https://laws-lois.justice.gc.ca"
_HUMAN = _BASE

_CODE_RE = re.compile(r"^[A-Za-z]-?\d+(?:\.\d+)?$")
_TITLE_RE = re.compile(r"<(?:LongTitle|ShortTitle)[^>]*>(.*?)</(?:LongTitle|ShortTitle)>", re.DOTALL)
_PIT_RE = re.compile(r'pit-date="([^"]+)"')
_INFORCE_RE = re.compile(r'in-force="([^"]+)"')
_AMENDED_RE = re.compile(r'lastAmendedDate="([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")


def _today() -> str:
    """Fallback modified date when the XML carries no point-in-time stamp."""
    return dt.datetime.now(dt.UTC).date().isoformat()


def _strip(text: str | None) -> str | None:
    if text is None:
        return None
    clean = _TAG_RE.sub("", text).strip()
    return clean or None


def _normalise_code(law_id: str) -> str | None:
    """Act code from ``law_id`` (``P-8.6``, ``C-46``, ``C-46.xml`` all work)."""
    code = law_id.strip().upper()
    if code.endswith(".XML"):
        code = code.removesuffix(".XML")
    if code.startswith("ACTS/"):
        code = code.removeprefix("ACTS/")
    code = code.rstrip("/")
    if not _CODE_RE.match(code):
        return None
    # Canonical form keeps the hyphen (``C46`` -> ``C-46``).
    if "-" not in code:
        code = f"{code[0]}-{code[1:]}"
    return code


class JusticeLawsAdapter(SourceAdapter):
    """Fetch consolidated federal Acts via the Justice Laws Website XML."""

    source_id: ClassVar[str] = "ca"
    name: ClassVar[str] = "Justice Laws Website (Department of Justice)"
    jurisdiction: ClassVar[str] = "CA"
    homepage: ClassVar[str] = "https://laws-lois.justice.gc.ca/eng/"
    license_note: ClassVar[str] = (
        "Crown copyright — reproduction of federal legislation permitted for non-commercial purposes with attribution"
    )
    crawl_delay_seconds: ClassVar[float] = 2.0
    text_format: ClassVar[str] = "xml"

    @override
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """Not offered: the legacy search form has no machine endpoint.

        Fetch by act code instead (``C-46`` Criminal Code, ``P-8.6`` PIPEDA);
        the human discovery surface is the acts index at
        https://laws-lois.justice.gc.ca/eng/acts/.
        """
        msg = (
            "Justice Laws Website offers no machine keyword search "
            f"(query={query!r}, limit={limit}); fetch by act code "
            "(e.g. 'C-46', 'P-8.6') listed at "
            "https://laws-lois.justice.gc.ca/eng/acts/"
        )
        raise NotAvailableBySourceError(msg)

    @override
    def fetch(self, law_id: str) -> Law:
        """Fetch one Act's consolidated XML as a :class:`Law`.

        *law_id* is the act code (``P-8.6``, ``C-46``); the ``.xml`` suffix
        and ``acts/`` prefix are tolerated. Title prefers the official
        ShortTitle (e.g. "Personal Information Protection and Electronic
        Documents Act"), falling back to the LongTitle; ``modified``
        carries the consolidation's point-in-time date.
        """
        code = _normalise_code(law_id)
        if code is None:
            msg = f"Unrecognised Justice Laws act code {law_id!r} (expected e.g. 'C-46', 'P-8.6')"
            raise ValueError(msg)
        url = f"{_BASE}/eng/XML/{code}.xml"
        body = self._get(url)
        titles = [_strip(m.group(1)) for m in _TITLE_RE.finditer(body)]
        titles = [t for t in titles if t]
        # ShortTitle renders first in practice, but take the *shortest*
        # candidate as the display title — robust to tag order.
        title = min(titles, key=len) if titles else code
        pit = _PIT_RE.search(body)
        amended = _AMENDED_RE.search(body)
        inforce = _INFORCE_RE.search(body)
        extras: list[tuple[str, str]] = [("format", "justice-xml")]
        if inforce:
            extras.append(("in_force", inforce.group(1)))
        if amended:
            extras.append(("last_amended", amended.group(1)))
        return Law(
            source=self.source_id,
            jurisdiction=self.jurisdiction,
            law_id=code,
            title=title,
            url=f"{_HUMAN}/eng/acts/{code}/",
            language="eng",
            modified=pit.group(1) if pit else _today(),
            text_url=url,
            extras=tuple(extras),
        )
