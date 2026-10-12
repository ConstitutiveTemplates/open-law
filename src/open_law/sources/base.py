"""Source adapter contract: one class per jurisdiction, one interface.

A source adapter wraps one official publication channel (an API, a bulk
data endpoint) and translates it into :mod:`open_law.models`. Adapters
must not scrape when a machine channel exists — the Good-future charter's
"feed first, API second, scraping last" starts at the API tier here, and
the shared fetcher still enforces robots.txt, rate limits, budgets, and
caching on every call.

The module-level helpers below are the adapters' shared toolkit: HTML
fragment cleanup, defensive JSON/XML parsing, and the small ``Law`` /
``LawSummary`` assembly idioms every adapter repeats. They live here so
the twelve adapters stay thin parsing shells over their own endpoints.
"""

from __future__ import annotations

import html as _html_module
import io
import json
import re
import xml.etree.ElementTree as ET
from abc import ABC
from abc import abstractmethod
from typing import ClassVar
from typing import cast

from defusedxml.ElementTree import fromstring

from open_law.fetcher import PoliteFetcher
from open_law.models import Law
from open_law.models import LawSummary
from open_law.text_extract import html_to_text
from open_law.text_extract import xml_to_text

__all__ = [
    "NotAvailableBySourceError",
    "SourceAdapter",
    "as_dict",
    "as_dict_list",
    "as_dict_or_none",
    "as_str",
    "child_by_local",
    "clamp_limit",
    "collapse_markup",
    "decode_json",
    "pairs",
    "parse_xml",
    "strip_markup",
    "xml_child_text",
    "xml_text",
]

_TAG_RE = re.compile(r"<[^>]+>")


class NotAvailableBySourceError(RuntimeError):
    """Raised when a source does not offer the requested capability.

    Callers catch this to branch: a CLI reports it as an error with the
    actionable next step the message carries (registration URL, index
    page to walk, ...).
    """


def strip_markup(text: str | None, *, unescape: bool = False) -> str | None:
    """Tag-stripped *text*, or None when empty/absent.

    Tags are removed without a replacement (``<strong>x</strong>`` →
    ``x``); with ``unescape=True`` entities resolve first (the GII
    ``htdig-keywords`` meta path).
    """
    if text is None:
        return None
    if unescape:
        text = _html_module.unescape(text)
    clean = _TAG_RE.sub("", text).strip()
    return clean or None


def collapse_markup(markup: str) -> str:
    """*markup* with tags replaced by spaces and whitespace collapsed."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", markup)).strip()


def as_str(value: object) -> str | None:
    """Non-empty *value* stringified, else None (JSON nulls and gaps)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_dict(value: object) -> dict[str, object]:
    """*value* as a dict, or ``{}`` when it is not one (defensive JSON)."""
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def as_dict_or_none(value: object) -> dict[str, object] | None:
    """*value* as a dict when it is one, else None (defensive JSON)."""
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def as_dict_list(value: object) -> list[dict[str, object]]:
    """*value* as a list of dicts, dropping non-dict entries."""
    if not isinstance(value, list):
        return []
    return [cast("dict[str, object]", entry) for entry in cast("list[object]", value) if isinstance(entry, dict)]


def pairs(candidates: tuple[tuple[str, object], ...]) -> tuple[tuple[str, str], ...]:
    """(key, value) pairs for the non-None *candidates*, stringified."""
    kept: list[tuple[str, str]] = []
    for key, value in candidates:
        text = as_str(value)
        if text is not None:
            kept.append((key, text))
    return tuple(kept)


def clamp_limit(limit: int) -> int:
    """A search ``limit`` clamped to at least 1."""
    return max(1, limit)


def decode_json(body: str, error: str) -> object:
    """``json.loads`` of *body*, raising ``ValueError(error)`` when malformed."""
    try:
        return cast("object", json.loads(body))
    except json.JSONDecodeError as exc:
        msg = error
        raise ValueError(msg) from exc


def parse_xml(body: str, error: str) -> ET.Element:
    """``defusedxml`` root of *body*, raising ``ValueError(error)`` when malformed."""
    try:
        return fromstring(body)
    except ET.ParseError as exc:
        msg = error
        raise ValueError(msg) from exc


def xml_text(element: ET.Element | None) -> str | None:
    """Stripped text of *element*, or None when empty/absent."""
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped or None


def xml_child_text(parent: ET.Element, tag: str) -> str | None:
    """Stripped text of *parent*'s first child named *tag*."""
    return xml_text(parent.find(tag))


def child_by_local(parent: ET.Element | None, local: str) -> ET.Element | None:
    """First child of *parent* whose tag ends with *local* (any namespace)."""
    if parent is None:
        return None
    for child in parent:
        if child.tag.rpartition("}")[2] == local:
            return child
    return None


class SourceAdapter(ABC):
    """Base class for one jurisdiction's publication channel.

    - ``source_id``: short id the CLI and the registry know
      (``"uk"``, ``"jp"``).
    - ``jurisdiction``: ISO 3166-1 alpha-2 code or ``"EU"``.
    - ``crawl_delay_seconds``: per-host delay; raise it above the default
      when the source's robots.txt asks for a Crawl-delay (as
      legislation.gov.uk does with 5).
    - ``http_headers``: content-negotiation headers the source requires
      (e.g. EUR-Lex's RDF ``Accept``).
    - ``text_format``: ``"html"``, ``"xml"``, ``"tmx"`` or ``"pdf"`` —
      which parser :meth:`full_text` should use for the document at
      ``text_url``.
    """

    source_id: ClassVar[str]
    name: ClassVar[str]
    jurisdiction: ClassVar[str]
    homepage: ClassVar[str]
    license_note: ClassVar[str]
    crawl_delay_seconds: ClassVar[float] = 1.0
    http_headers: ClassVar[dict[str, str]] = {}
    text_format: ClassVar[str] = "html"

    def __init__(self, fetcher: PoliteFetcher) -> None:
        self.fetcher: PoliteFetcher = fetcher

    def _get(self, url: str) -> str:
        """Polite GET of a known machine endpoint: robots + budget + cache.

        ``discover=False`` skips the feed/API probing preflight — the
        adapter *is* the API strategy, and probing a known endpoint's
        origin for feeds would only add load.
        """
        return self.fetcher.fetch_text(url, discover=False)

    def _get_bytes(self, url: str) -> bytes:
        """Polite GET of a known endpoint as bytes (for PDFs)."""
        return self.fetcher.fetch_bytes(url, discover=False)

    def _full_text_pdf(self, law_id: str, text_url: str | None) -> str:
        """Extracted text of the PDF at *text_url* (pypdf, when installed)."""
        if text_url is None:
            msg = f"{law_id!r} has no machine-readable full text"
            raise NotAvailableBySourceError(msg)
        try:
            import pypdf  # type: ignore[import-not-found,import-untyped]
        except ImportError as exc:
            msg = (
                f"full text of {law_id!r} is a PDF; install the pdf extra "
                f"with `pip install open-law[pdf]` to extract it (download at {text_url})"
            )
            raise NotAvailableBySourceError(msg) from exc
        data = self._get_bytes(text_url)
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            msg = f"failed to extract PDF text for {law_id!r}: {exc}"
            raise NotAvailableBySourceError(msg) from exc
        text = "\n".join(pages).strip()
        # Fall back to empty string when pypdf returns no text (scanned PDF).
        return text

    def _full_text_markup(self, law_id: str, text_url: str | None) -> str:
        """Plain text of the document at *text_url* via ``text_format``."""
        if text_url is None:
            msg = f"{law_id!r} has no machine-readable full text"
            raise NotAvailableBySourceError(msg)
        body = self._get(text_url)
        if self.text_format == "xml":
            return xml_to_text(body)
        return html_to_text(body)

    def full_text(self, law_id: str) -> str:
        """The law's full text as plain text, refetching ``text_url``.

        The on-disk cache makes the second fetch free. Conversion follows
        ``text_format``: ``xml`` (statute APIs ship the text inside the
        XML tree) extracts character data; ``html`` strips the page to
        readable text. ``pdf`` sources extract via ``pypdf`` when
        installed — otherwise the error tells the caller to
        ``pip install open-law[pdf]``.
        """
        law = self.fetch(law_id)
        if self.text_format == "pdf":
            return self._full_text_pdf(law_id, law.text_url)
        return self._full_text_markup(law_id, law.text_url)

    @abstractmethod
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """List laws matching *query*, at most *limit* results."""

    @abstractmethod
    def fetch(self, law_id: str) -> Law:
        """Fetch one law by its source-native *law_id*."""
