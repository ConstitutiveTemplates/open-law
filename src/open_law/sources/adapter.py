"""One jurisdiction's publication channel: the adapter contract.

A source adapter wraps one official publication channel (an API, a bulk
data endpoint) and translates it into :mod:`open_law.models`. Adapters
must not scrape when a machine channel exists — the Good-future
charter's "feed first, API second, scraping last" starts at the API
tier here, and the shared fetcher still enforces robots.txt, rate
limits, budgets, and caching on every call.

Parsing idioms live in :mod:`open_law.sources.parsing` (defensive
JSON/XML) and :mod:`open_law.sources.markup` (HTML cleanup); this
module owns only the abstract adapter plus PDF/full-text fetching.
"""

from __future__ import annotations

import io
from abc import ABC
from abc import abstractmethod
from typing import ClassVar

from open_law.fetcher import PoliteFetcher
from open_law.models import Law
from open_law.models import LawSummary
from open_law.text_extract import html_to_text
from open_law.text_extract import xml_to_text

__all__ = ["NotAvailableBySourceError", "SourceAdapter"]


class NotAvailableBySourceError(RuntimeError):
    """Raised when a source does not offer the requested capability.

    Callers catch this to branch: a CLI reports it as an error with the
    actionable next step the message carries (registration URL, index
    page to walk, ...).
    """


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
