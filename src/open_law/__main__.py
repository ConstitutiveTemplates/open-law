"""Interface for ``python -m open_law`` and the ``open-law`` console script.

Subcommands cover the source-adapter workflow end to end:

- ``sources``: list the registered jurisdiction adapters;
- ``preflight URL``: the fetcher's judgement about a URL (robots,
  access, feed, API, budget) — it sends polite, rate-limited probes:
  robots.txt, a HEAD of the URL, and feed/API discovery requests;
- ``search SOURCE QUERY``: title-search one source's law list;
- ``fetch SOURCE LAW_ID``: fetch one law and print it as JSON;
- ``text SOURCE LAW_ID``: print the law's full text as plain text;
- ``dump SOURCE LAW_ID...``: fetch several laws and consolidate them as
  JSONL (stdout, or a file via ``--out``); ids may also come from a
  file or stdin via ``--ids-from``, one per line.
- ``coverage CORPUS.jsonl``: country x topic matrix over a dumped
  corpus, with a per-country list of topics the corpus does not cover.

Errors surface as ``open-law: error: ...`` on stderr with exit code 2;
unexpected failures still raise so operators see the real traceback.

Argument shapes live in :mod:`open_law.cli_parser`, output plumbing in
:mod:`open_law.cli_io`, adapter-bound commands in
:mod:`open_law.cli_sources`, and corpus-bound commands in
:mod:`open_law.cli_analysis`. This module only dispatches argv to them.

``preflight`` is re-exported here (and resolved at call time below) so
tests can ``monkeypatch.setattr(cli, "preflight", fake)`` exactly as
before the CLI split.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import cast

from .cli_analysis import run_analysis_commands
from .cli_io import print_json
from .cli_parser import ANALYSIS_COMMANDS
from .cli_parser import WAYBACK_COMMANDS
from .cli_parser import build_parser
from .cli_sources import AdapterFactory
from .cli_sources import cmd_sources
from .cli_sources import run_source_commands
from .fetcher import preflight
from .logging_setup import logger
from .sources import open_adapter

__all__ = [
    "AdapterFactory",
    "main",
    "preflight",
]


def main(
    args: Sequence[str] | None = None,
    *,
    adapter_factory: AdapterFactory | None = None,
) -> None:
    """Argument parser for the CLI.

    ``adapter_factory`` replaces :func:`open_law.sources.open_adapter`
    (tests inject offline fetchers through it); production callers leave
    it unset.
    """
    parser = build_parser()
    parsed = parser.parse_args(args)
    build_adapter: AdapterFactory = adapter_factory or open_adapter
    command = getattr(parsed, "command", None)
    logger.info("open_law_invoked", command=command)
    try:
        if command in ANALYSIS_COMMANDS:
            run_analysis_commands(cast("str", command), parsed)
        elif command == "sources":
            cmd_sources()
        elif command == "preflight":
            # Module-global lookup: monkeypatching ``cli.preflight`` swaps
            # the judgement without touching the network.
            print_json(asdict(preflight(cast("str", parsed.url))))
        elif command in (*WAYBACK_COMMANDS, "search"):
            run_source_commands(cast("str", command), parsed, build_adapter)
    except (ValueError, RuntimeError, LookupError, TypeError) as exc:
        parser.exit(2, f"open-law: error: {exc}\n")


if __name__ == "__main__":
    main()
