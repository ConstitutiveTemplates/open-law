"""CLI argument parsing: every subcommand's argv shape in one place.

Owns :func:`build_parser` (source-adapter workflow: ``sources``,
``preflight``, ``search``/``fetch``/``text``/``dump``, plus the
corpus-analysis trio ``coverage``/``correspond``/``taxonomy``) and the
command-group tuples the dispatcher in :mod:`open_law.__main__` uses
to route. Command implementations live in :mod:`open_law.cli_sources`
(adapter-bound) and :mod:`open_law.cli_analysis` (corpus-bound).
"""

from __future__ import annotations

import argparse
from argparse import ArgumentParser

from open_law import __version__

__all__ = ["ANALYSIS_COMMANDS", "WAYBACK_COMMANDS", "build_parser"]

WAYBACK_COMMANDS = ("fetch", "text", "dump")
ANALYSIS_COMMANDS = ("coverage", "correspond", "taxonomy")


def build_parser() -> ArgumentParser:
    """The CLI parser: shared by ``main`` and its error paths."""
    parser = ArgumentParser(prog="open-law", description="Scrape and consolidate legislation from around the world.")
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=__version__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sources", help="list the registered jurisdiction adapters")

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="judge a URL (robots/access/feed/API/budget) via polite probes: robots.txt, HEAD, feed/API discovery",
    )
    preflight_parser.add_argument("url", help="the URL to judge")

    search_parser = subparsers.add_parser("search", help="title-search one source")
    search_parser.add_argument("source", help="source id (see 'open-law sources')")
    search_parser.add_argument("query", help="title text to search for")
    search_parser.add_argument("--limit", type=int, default=10, help="max results (default 10)")

    _add_wayback_parser(subparsers, "fetch", "fetch one law as JSON")
    _add_wayback_parser(subparsers, "text", "fetch one law's full text as plain text")
    dump_parser = _add_wayback_parser(subparsers, "dump", "fetch several laws and consolidate as JSONL")
    dump_parser.add_argument("law_ids", nargs="*", help="source-native ids (or use --ids-from)")
    dump_parser.add_argument("--ids-from", help="file with one id per line ('-' for stdin)")
    dump_parser.add_argument("--out", help="JSONL file to write (default: stdout)")

    coverage_parser = subparsers.add_parser(
        "coverage", help="country x topic coverage matrix from a dumped JSONL corpus"
    )
    coverage_parser.add_argument("corpus", help="JSONL file of dumped laws ('-' for stdin)")
    coverage_parser.add_argument("--json", action="store_true", help="emit the matrix as JSON instead of a table")
    coverage_parser.add_argument("--taxonomy", help="expert taxonomy JSON (default: built-in)")
    coverage_parser.add_argument("--annotations", help="expert annotations JSON overriding the classifier")

    correspond_parser = subparsers.add_parser(
        "correspond",
        help="candidate cross-country correspondences from a dumped corpus (for human review)",
    )
    correspond_parser.add_argument("corpus", help="JSONL file of dumped laws ('-' for stdin)")
    correspond_parser.add_argument("--taxonomy", help="expert taxonomy JSON (default: built-in)")
    correspond_parser.add_argument("--annotations", help="expert annotations JSON overriding the classifier")
    correspond_parser.add_argument(
        "--min-similarity", type=float, default=0.5, help="title similarity floor (default 0.5)"
    )
    correspond_parser.add_argument(
        "--year-window", type=int, default=5, help="max year gap between candidates (default 5)"
    )

    taxonomy_parser = subparsers.add_parser("taxonomy", help="export the built-in topic taxonomy for expert editing")
    taxonomy_parser.add_argument("--export", help="write the taxonomy JSON to this path ('-' for stdout)")
    return parser


def _add_wayback_parser(
    subparsers: argparse._SubParsersAction[ArgumentParser], name: str, help_text: str
) -> ArgumentParser:
    """A source-bound subcommand parser with ``source``/``law_id``/``--wayback``."""
    cmd_parser = subparsers.add_parser(name, help=help_text)
    cmd_parser.add_argument("source", help="source id (see 'open-law sources')")
    if name != "dump":
        cmd_parser.add_argument("law_id", help="source-native id, e.g. 'ukpga/1989/6' or a CELEX")
    cmd_parser.add_argument("--wayback", action="store_true", help="fall back to the Wayback Machine on failure")
    return cmd_parser
