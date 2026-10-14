"""Adapter-bound CLI commands: search/fetch/text/dump/sources.

Each command takes an already-constructed
:class:`open_law.sources.adapter.SourceAdapter` (built by the
dispatcher honouring ``--wayback``/``--budget``/``--delay``/``--contact``)
and prints its result. Adapter construction itself — the factory plus the
politeness flags — lives here too, so :mod:`open_law.__main__` only routes
argv.

``dump`` writes what it fetched before a budget stop and reports the ids
it never reached, so a long harvest resumes instead of restarting.
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
from open_law.fetch_models import BudgetExceededError
from open_law.models import Law
from open_law.models import LawSummary
from open_law.sources import ADAPTERS
from open_law.sources.adapter import SourceAdapter

__all__ = ["AdapterFactory", "open_cli_adapter", "run_source_commands"]

AdapterFactory = Callable[[str], SourceAdapter]

# Suffix of the sidecar id list a stopped dump leaves next to ``--out``.
REMAINING_SUFFIX = ".remaining"


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

    A failure that is not the host budget (a missing act, a denied page)
    still leaves no partial file behind: nothing is written until the
    batch finishes. Budget exhaustion is different — the work so far is
    written and the ids that were not reached are reported (and, with
    ``--out``, saved next to the file as ``<out>.remaining``), because
    stopping at the budget is the charter working as intended, not a bug.
    """
    laws: list[Law] = []
    for index, law_id in enumerate(law_ids):
        try:
            laws.append(adapter.fetch(law_id))
        except BudgetExceededError as exc:
            remaining = law_ids[index:]
            write_dump(laws, out_path)
            report_budget_stop(adapter, len(laws), len(law_ids), remaining, out_path)
            msg = f"{exc} — {resume_hint(adapter, remaining, out_path)}"
            raise BudgetExceededError(msg) from exc
    write_dump(laws, out_path)
    maybe_print_wayback(adapter)


def write_dump(laws: list[Law], out_path: str | None) -> int:
    """Write *laws* as JSONL to *out_path* (or stdout); returns the count."""
    if out_path is None:
        return dump_jsonl(laws, sys.stdout)
    with pathlib.Path(out_path).open("w", encoding="utf-8") as out:
        return dump_jsonl(laws, out)


def report_budget_stop(
    adapter: SourceAdapter,
    written: int,
    attempted: int,
    remaining: list[str],
    out_path: str | None,
) -> None:
    """Announce where a budget-stopped dump got to, and how to resume."""
    print(
        f"open-law: host budget reached after {written} of {attempted} law(s); {len(remaining)} id(s) not fetched",
        file=sys.stderr,
    )
    if out_path is None:
        for law_id in remaining:
            print(law_id, file=sys.stderr)
        return
    remaining_path = pathlib.Path(f"{out_path}{REMAINING_SUFFIX}")
    remaining_path.write_text("".join(f"{law_id}\n" for law_id in remaining), encoding="utf-8")
    print(f"open-law: resume with: {resume_command(adapter, remaining_path, out_path)}", file=sys.stderr)


def resume_command(adapter: SourceAdapter, remaining_path: pathlib.Path, out_path: str) -> str:
    """The command that continues this dump from *remaining_path*.

    The suggested budget is double the one that just ran out: a harvest
    large enough to stop at 100 will not finish at 100, and the operator
    can raise it further by hand.
    """
    budget = max(adapter.fetcher.config.max_requests_per_host * 2, 1)
    return f"open-law dump {adapter.source_id} --ids-from {remaining_path} --out {out_path} --budget {budget}"


def resume_hint(adapter: SourceAdapter, remaining: list[str], out_path: str | None) -> str:
    """One-line resume guidance for the budget-stop error message."""
    if out_path is None:
        return f"{len(remaining)} id(s) were not fetched (see stderr); raise --budget and re-run"
    return f"resume with: {resume_command(adapter, pathlib.Path(f'{out_path}{REMAINING_SUFFIX}'), out_path)}"


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
        adapter.fetcher.set_config(replace(cfg, wayback_fallback=True))


def apply_politeness(adapter: SourceAdapter, parsed: argparse.Namespace) -> None:
    """Apply ``--budget`` / ``--delay`` / ``--contact`` to *adapter*'s fetcher.

    The values a run needs are rarely the adapter's defaults — a first
    pass over a large index wants a bigger budget, a slow host wants a
    longer delay — and the contact must be raisable from the command line
    when the environment cannot carry it.
    """
    config = adapter.fetcher.config
    budget = cast("int | None", getattr(parsed, "budget", None))
    delay = cast("float | None", getattr(parsed, "delay", None))
    contact = cast("str | None", getattr(parsed, "contact", None))
    if budget is None and delay is None and contact is None:
        return
    if budget is not None:
        if budget < 1:
            msg = f"--budget must be at least 1 request, got {budget}"
            raise ValueError(msg)
        config = replace(config, max_requests_per_host=budget)
    if delay is not None:
        if delay < 0:
            msg = f"--delay must not be negative, got {delay}"
            raise ValueError(msg)
        config = replace(config, delay_seconds=delay)
    if contact is not None:
        config = replace(config, contact=contact)
    adapter.fetcher.set_config(config)


def open_cli_adapter(factory: AdapterFactory, parsed: argparse.Namespace) -> SourceAdapter:
    """Build the adapter for a source-bound command under the CLI's flags."""
    adapter = factory(cast("str", parsed.source))
    if getattr(parsed, "wayback", False):
        enable_wayback(adapter)
    apply_politeness(adapter, parsed)
    return adapter


def run_source_commands(command: str, parsed: argparse.Namespace, factory: AdapterFactory) -> None:
    """Dispatch the adapter-bound subcommands (search/fetch/text/dump)."""
    if command == "search":
        adapter = open_cli_adapter(factory, parsed)
        cmd_search(adapter, cast("str", parsed.query), cast("int", parsed.limit))
    elif command == "fetch":
        cmd_fetch(open_cli_adapter(factory, parsed), cast("str", parsed.law_id))
    elif command == "text":
        cmd_text(open_cli_adapter(factory, parsed), cast("str", parsed.law_id))
    elif command == "dump":
        cmd_dump(
            open_cli_adapter(factory, parsed),
            read_ids(cast("str | None", parsed.ids_from), cast("list[str]", parsed.law_ids)),
            cast("str | None", parsed.out),
        )
