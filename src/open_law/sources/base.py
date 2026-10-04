"""Source adapter contract: one class per jurisdiction, one interface.

A source adapter wraps one official publication channel (an API, a bulk
data endpoint) and translates it into :mod:`open_law.models`. Adapters
must not scrape when a machine channel exists — the Good-future charter's
"feed first, API second, scraping last" starts at the API tier here, and
the shared fetcher still enforces robots.txt, rate limits, budgets, and
caching on every call.
"""

from __future__ import annotations

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

    Not an outage: the channel genuinely is not offered — a statute
    registry without search, or full texts behind a registration the
    operator has not completed. The message carries the actionable next
    step (which endpoint, which registration) instead of a bare failure.
    """


class SourceAdapter(ABC):
    """Base class for one jurisdiction's publication channel.

    Class attributes describe the source for :command:`open-law sources`
    and drive the default fetcher's politeness:

    - ``crawl_delay_seconds``: per-host delay; raise it above the default
      when the source's robots.txt asks for a Crawl-delay (as
      legislation.gov.uk does with 5).
    - ``http_headers``: content-negotiation headers the source requires
      (EU CELLAR needs an ``Accept``), merged into the default client.
    - ``license_note``: what the source says about reusing its data —
      recorded per source because it differs per jurisdiction.
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

    def full_text(self, law_id: str) -> str:
        """The law's full text as plain text, refetching ``text_url``.

        The on-disk cache makes the second fetch free. Conversion follows
        ``text_format``: ``xml`` (statute APIs ship the text inside the
        XML tree) extracts character data; ``html`` strips the page to
        readable text. ``pdf`` sources refuse — the text lives in a
        binary document, and the caller should download ``text_url``
        instead.
        """
        law = self.fetch(law_id)
        if self.text_format == "pdf":
            msg = f"full text of {law_id!r} is a PDF; download {law.text_url or 'the document from the source site'}"
            raise NotAvailableBySourceError(msg)
        if law.text_url is None:
            msg = f"{law_id!r} has no machine-readable full text"
            raise NotAvailableBySourceError(msg)
        body = self._get(law.text_url)
        if self.text_format == "xml":
            return xml_to_text(body)
        return html_to_text(body)

    @abstractmethod
    def search(self, query: str, *, limit: int = 10) -> list[LawSummary]:
        """List laws matching *query*, at most *limit* results."""

    @abstractmethod
    def fetch(self, law_id: str) -> Law:
        """Fetch one law by its source-native *law_id*."""
