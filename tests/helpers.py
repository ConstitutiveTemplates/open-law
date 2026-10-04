"""Shared types for the source-adapter tests.

The offline fixtures live in ``conftest.py``; this module gives their
injected callables precise types (pytest fixture parameters have no
magic type inference). Imported as ``tests.helpers`` — a namespace
package import made resolvable by pytest's ``pythonpath`` setting.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from open_law.sources.base import SourceAdapter

Handler = Callable[[httpx.Request], httpx.Response]
FixtureLoader = Callable[[str], str]


class RecordingSite(Protocol):
    """Fake origin serving captured bodies by path, recording request URLs."""

    def __call__(
        self,
        responses: dict[str, str],
        seen: list[str],
        robots: str = ...,
    ) -> Handler: ...


class Offline(Protocol):
    """Wire an adapter class to a zero-delay offline fetcher + *handler*."""

    def __call__(self, adapter_cls: type[SourceAdapter], handler: Handler) -> SourceAdapter: ...
