"""Registry of jurisdiction source adapters.

``ADAPTERS`` maps the ``source_id`` every adapter declares to its class;
:func:`open_adapter` is the single construction point the CLI (and any
embedding application) uses. Adding a jurisdiction means adding a
:class:`open_law.sources.base.SourceAdapter` subclass module and one
registry line here — nothing else.
"""

from __future__ import annotations

from open_law.fetcher import FetchConfig
from open_law.fetcher import PoliteFetcher
from open_law.sources.base import NotAvailableBySourceError
from open_law.sources.base import SourceAdapter
from open_law.sources.bd import BangladeshLawsAdapter
from open_law.sources.ca import JusticeLawsAdapter
from open_law.sources.eu import EurlexAdapter
from open_law.sources.jp import EgovAdapter
from open_law.sources.kr import KoreaLawAdapter
from open_law.sources.la import LaoGazetteAdapter
from open_law.sources.np import NepalLawCommissionAdapter
from open_law.sources.uk import LegislationGovUkAdapter
from open_law.sources.us import EcfrAdapter

__all__ = [
    "ADAPTERS",
    "NotAvailableBySourceError",
    "SourceAdapter",
    "default_fetcher",
    "open_adapter",
]

ADAPTERS: dict[str, type[SourceAdapter]] = {
    LegislationGovUkAdapter.source_id: LegislationGovUkAdapter,
    EgovAdapter.source_id: EgovAdapter,
    KoreaLawAdapter.source_id: KoreaLawAdapter,
    LaoGazetteAdapter.source_id: LaoGazetteAdapter,
    NepalLawCommissionAdapter.source_id: NepalLawCommissionAdapter,
    BangladeshLawsAdapter.source_id: BangladeshLawsAdapter,
    EurlexAdapter.source_id: EurlexAdapter,
    EcfrAdapter.source_id: EcfrAdapter,
    JusticeLawsAdapter.source_id: JusticeLawsAdapter,
}


def default_fetcher(adapter_cls: type[SourceAdapter]) -> PoliteFetcher:
    """A :class:`PoliteFetcher` tuned to *adapter_cls*'s politeness needs.

    Carries the adapter's ``crawl_delay_seconds`` (robots.txt Crawl-delay
    requests, such as legislation.gov.uk's 5 s) and its content
    negotiation ``http_headers``, so every adapter call is polite and
    correctly negotiated without the adapter touching raw httpx.
    """
    config = FetchConfig(delay_seconds=adapter_cls.crawl_delay_seconds)
    return PoliteFetcher(config, headers=dict(adapter_cls.http_headers))


def open_adapter(source_id: str, fetcher: PoliteFetcher | None = None) -> SourceAdapter:
    """Instantiate the adapter registered under *source_id*.

    *fetcher* injects a custom (test/offline) fetcher; without one, the
    adapter gets :func:`default_fetcher`. Unknown ids raise ``ValueError``
    listing the known ids.
    """
    try:
        adapter_cls = ADAPTERS[source_id]
    except KeyError:
        known = ", ".join(sorted(ADAPTERS))
        msg = f"unknown source {source_id!r}; known sources: {known}"
        raise ValueError(msg) from None
    return adapter_cls(fetcher or default_fetcher(adapter_cls))
