"""Adapter-bound CLI commands: search/fetch/text/dump/sources.

Each command takes an already-constructed
:class:`open_law.sources.adapter.SourceAdapter` (built by the
dispatcher honouring ``--wayback``) and prints its result. Adapter
construction itself — the factory plus the ``--wayback`` flag wiring —
lives here too, so :mod:`open_law.__main__` only routes argv.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import replace
from typing import cast

from open_law.cli_io import maybe_print_wayback
from open_law.cli_io import print_json
from open_law.dataset import dump_jsonl
from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources import ADAPTERS
from open_law.sources.adapter import SourceAdapter

__all__ = ["AdapterFactory", "open_wayback_adapter", "run_source_commands"]

AdapterFactory = Callable[[str], SourceAdapter]


def cmd_sources() -> None:
    """Print the adapter registry as one line per source."""
    for _source_id, adapter_cls in sorted(ADAPTERS.items()):
        print(
            f"{adapter_cls.source_id}\t{adapter_cls.jurisdiction}\t{adapter_cls.channel}\t"
            f"{adapter_cls.name}\t{adapter_cls.homepage}\t{adapter_cls.license_note}"
        )


def cmd_search(adapter: SourceAdapter, query: str, limit: int) -> None:
    """Print adapter search results as a JSON list."""
    results: list[LawSummary] = adapter.search(query, limit=limit)
    print_json([asdict(summary) for summary in results])


def cmd_fetch(adapter: SourceAdapter, law_id: str) -> None:
    """Print one fetched law as a JSON object."""
    law: Law = adapter.fetch(law_id)
    print_json(asdict(law))
    maybe_print_wayback(adapter)


def cmd_text(adapter: SourceAdapter, law_id: str) -> None:
    """Print one law's full text as plain text."""
    print(adapter.full_text(law_id))
    maybe_print_wayback(adapter)


def cmd_dump(adapter: SourceAdapter, law_ids: list[str], out_path: str | None) -> None:
    """Fetch every id and consolidate the results as JSONL.

    All fetches happen before anything is written, so a failure mid-batch
    leaves no partial file behind.
    """
    laws = [adapter.fetch(law_id) for law_id in law_ids]
    if out_path is None:
        dump_jsonl(laws, sys.stdout)
    else:
        with pathlib.Path(out_path).open("w", encoding="utf-8") as out:
            dump_jsonl(laws, out)
    maybe_print_wayback(adapter)


def read_ids(ids_from: str | None, law_ids: list[str]) -> list[str]:
    """Merge explicit ids with ids read one-per-line from *ids_from*.

    ``--ids-from -`` reads from stdin. Blank lines are skipped; neither
    source alone nor the combination may end up empty.
    """
    ids = list(law_ids)
    if ids_from is not None:
        if ids_from == "-":
            ids.extend(line.strip() for line in sys.stdin if line.strip())
        else:
            text = pathlib.Path(ids_from).read_text(encoding="utf-8")
            ids.extend(line.strip() for line in text.splitlines() if line.strip())
    if not ids:
        msg = "no law ids given (pass ids on the command line or --ids-from)"
        raise ValueError(msg)
    return ids


def enable_wayback(adapter: SourceAdapter) -> None:
    """Enable Wayback fallback on *adapter*'s fetcher in place."""
    cfg = adapter.fetcher.config
    if not cfg.wayback_fallback:
        adapter.fetcher.config = replace(cfg, wayback_fallback=True)


def open_wayback_adapter(factory: AdapterFactory, parsed: argparse.Namespace) -> SourceAdapter:
    """Build the adapter for a source-bound command, honouring ``--wayback``."""
    adapter = factory(cast("str", parsed.source))
    if getattr(parsed, "wayback", False):
        enable_wayback(adapter)
    return adapter


def run_source_commands(command: str, parsed: argparse.Namespace, factory: AdapterFactory) -> None:
    """Dispatch the adapter-bound subcommands (search/fetch/text/dump)."""
    if command == "search":
        cmd_search(
            factory(cast("str", parsed.source)),
            cast("str", parsed.query),
            cast("int", parsed.limit),
        )
    elif command == "fetch":
        cmd_fetch(open_wayback_adapter(factory, parsed), cast("str", parsed.law_id))
    elif command == "text":
        cmd_text(open_wayback_adapter(factory, parsed), cast("str", parsed.law_id))
    elif command == "dump":
        cmd_dump(
            open_wayback_adapter(factory, parsed),
            read_ids(cast("str | None", parsed.ids_from), cast("list[str]", parsed.law_ids)),
            cast("str | None", parsed.out),
        )
