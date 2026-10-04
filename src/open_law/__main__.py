"""Interface for ``python -m open_law`` and the ``open-law`` console script.

Subcommands cover the source-adapter workflow end to end:

- ``sources``: list the registered jurisdiction adapters;
- ``preflight URL``: the fetcher's judgement about a URL (feed, API,
  robots, budget) without fetching anything;
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
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from argparse import ArgumentParser
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import asdict
from typing import TextIO
from typing import cast

from . import __version__
from .correspond import find_correspondences
from .coverage import coverage_matrix
from .coverage import gap_report
from .coverage import iter_corpus
from .coverage import load_annotations
from .dataset import dump_jsonl
from .fetcher import preflight
from .logging_setup import logger
from .models import Law
from .models import LawSummary
from .sources import ADAPTERS
from .sources import SourceAdapter
from .sources import open_adapter
from .topics import DEFAULT_TOPICS
from .topics import export_taxonomy_json
from .topics import load_taxonomy

__all__ = ["main"]

AdapterFactory = Callable[[str], SourceAdapter]


def _build_parser() -> ArgumentParser:
    """The CLI parser: shared by :func:`main` and its error paths."""
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
        "preflight", help="judge a URL (feed/API/robots/budget) without fetching it"
    )
    preflight_parser.add_argument("url", help="the URL to judge")

    search_parser = subparsers.add_parser("search", help="title-search one source")
    search_parser.add_argument("source", help="source id (see 'open-law sources')")
    search_parser.add_argument("query", help="title text to search for")
    search_parser.add_argument("--limit", type=int, default=10, help="max results (default 10)")

    fetch_parser = subparsers.add_parser("fetch", help="fetch one law as JSON")
    fetch_parser.add_argument("source", help="source id (see 'open-law sources')")
    fetch_parser.add_argument("law_id", help="source-native id, e.g. 'ukpga/1989/6' or a CELEX")

    text_parser = subparsers.add_parser("text", help="fetch one law's full text as plain text")
    text_parser.add_argument("source", help="source id (see 'open-law sources')")
    text_parser.add_argument("law_id", help="source-native id, e.g. 'ukpga/1989/6' or a CELEX")

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

    dump_parser = subparsers.add_parser("dump", help="fetch several laws and consolidate as JSONL")
    dump_parser.add_argument("source", help="source id (see 'open-law sources')")
    dump_parser.add_argument("law_ids", nargs="*", help="source-native ids (or use --ids-from)")
    dump_parser.add_argument("--ids-from", help="file with one id per line ('-' for stdin)")
    dump_parser.add_argument("--out", help="JSONL file to write (default: stdout)")
    return parser


def _print_json(payload: object) -> None:
    """Print *payload* as readable, non-escaped JSON."""
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _cmd_sources() -> None:
    """Print the adapter registry as one line per source."""
    for _source_id, adapter_cls in sorted(ADAPTERS.items()):
        print(
            f"{adapter_cls.source_id}\t{adapter_cls.jurisdiction}\t"
            f"{adapter_cls.name}\t{adapter_cls.homepage}\t{adapter_cls.license_note}"
        )


def _cmd_preflight(url: str) -> None:
    """Print the fetcher's preflight judgement for *url*."""
    judged = preflight(url)
    _print_json(asdict(judged))


def _cmd_search(adapter: SourceAdapter, query: str, limit: int) -> None:
    """Print adapter search results as a JSON list."""
    results: list[LawSummary] = adapter.search(query, limit=limit)
    _print_json([asdict(summary) for summary in results])


def _cmd_fetch(adapter: SourceAdapter, law_id: str) -> None:
    """Print one fetched law as a JSON object."""
    law: Law = adapter.fetch(law_id)
    _print_json(asdict(law))


def _open_corpus(corpus_path: str) -> TextIO:
    """An open handle on a dumped corpus file, or stdin for '-' (never closed)."""
    if corpus_path == "-":
        return sys.stdin
    return pathlib.Path(corpus_path).open(encoding="utf-8")


def _cmd_coverage(
    corpus_path: str,
    *,
    as_json: bool,
    taxonomy_path: str | None,
    annotations_path: str | None,
) -> None:
    """Print the country-by-topic coverage matrix for a dumped corpus."""
    topics = load_taxonomy(taxonomy_path)
    annotations = load_annotations(annotations_path) if annotations_path else None
    all_topics = dict(topics)
    if annotations:
        for annotated in annotations.values():
            for topic in annotated:
                all_topics.setdefault(topic, (topic,))
    corpus = _open_corpus(corpus_path)
    try:
        matrix = coverage_matrix(corpus, topics, annotations)
    finally:
        if corpus is not sys.stdin:
            corpus.close()
    if as_json:
        _print_json(
            {
                jurisdiction: {
                    "counts": {topic: matrix.counts.get((jurisdiction, topic), 0) for topic in sorted(all_topics)},
                    "missing": list(matrix.missing_topics(jurisdiction, all_topics)),
                }
                for jurisdiction in matrix.jurisdictions
            }
        )
    else:
        print(gap_report(matrix, all_topics))


def _cmd_correspond(
    corpus_path: str,
    *,
    taxonomy_path: str | None,
    annotations_path: str | None,
    min_similarity: float,
    year_window: int,
) -> None:
    """Print candidate cross-country correspondences for human review."""
    topics = load_taxonomy(taxonomy_path)
    annotations = load_annotations(annotations_path) if annotations_path else None
    all_topics = dict(topics)
    if annotations:
        for annotated in annotations.values():
            for topic in annotated:
                all_topics.setdefault(topic, (topic,))
    corpus = _open_corpus(corpus_path)
    try:
        entries = list(iter_corpus(corpus))
    finally:
        if corpus is not sys.stdin:
            corpus.close()
    candidates = find_correspondences(
        entries,
        topics,
        annotations,
        min_similarity=min_similarity,
        year_window=year_window,
    )
    if not candidates:
        print("no candidate correspondences found — this means no candidate pairs, not that the laws do not correspond")
        return
    print("candidates for human review (similarity is title-based, not equivalence):")
    for candidate in candidates:
        print(
            f"{candidate.similarity:.3f}  [{candidate.topic}] "
            f"{candidate.jurisdiction_a} {candidate.year_a or ''} {candidate.title_a!r}"
            f"  <->  "
            f"{candidate.jurisdiction_b} {candidate.year_b or ''} {candidate.title_b!r}"
        )


def _cmd_taxonomy(export_path: str | None) -> None:
    """Export the built-in taxonomy as the expert-editable JSON schema."""
    if export_path is None or export_path == "-":
        sys.stdout.write(export_taxonomy_json(DEFAULT_TOPICS))
    else:
        pathlib.Path(export_path).write_text(export_taxonomy_json(DEFAULT_TOPICS), encoding="utf-8")


def _read_ids(ids_from: str | None, law_ids: list[str]) -> list[str]:
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


def _cmd_text(adapter: SourceAdapter, law_id: str) -> None:
    """Print one law's full text as plain text."""
    print(adapter.full_text(law_id))


def _cmd_dump(adapter: SourceAdapter, law_ids: list[str], out_path: str | None) -> None:
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


def _run_analysis_commands(command: str, parsed: argparse.Namespace) -> None:
    """Dispatch the corpus-analysis subcommands (coverage/correspond/taxonomy)."""
    if command == "coverage":
        _cmd_coverage(
            cast("str", parsed.corpus),
            as_json=cast("bool", parsed.json),
            taxonomy_path=cast("str | None", parsed.taxonomy),
            annotations_path=cast("str | None", parsed.annotations),
        )
    elif command == "correspond":
        _cmd_correspond(
            cast("str", parsed.corpus),
            taxonomy_path=cast("str | None", parsed.taxonomy),
            annotations_path=cast("str | None", parsed.annotations),
            min_similarity=cast("float", parsed.min_similarity),
            year_window=cast("int", parsed.year_window),
        )
    elif command == "taxonomy":
        _cmd_taxonomy(cast("str | None", parsed.export))


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
    parser = _build_parser()
    parsed = parser.parse_args(args)
    build_adapter: AdapterFactory = adapter_factory or open_adapter
    command = getattr(parsed, "command", None)
    logger.info("open_law_invoked", command=command)
    try:
        if command in ("coverage", "correspond", "taxonomy"):
            _run_analysis_commands(cast("str", command), parsed)
        elif command == "sources":
            _cmd_sources()
        elif command == "preflight":
            _cmd_preflight(cast("str", parsed.url))
        elif command == "search":
            _cmd_search(
                build_adapter(cast("str", parsed.source)),
                cast("str", parsed.query),
                cast("int", parsed.limit),
            )
        elif command == "fetch":
            _cmd_fetch(build_adapter(cast("str", parsed.source)), cast("str", parsed.law_id))
        elif command == "text":
            _cmd_text(build_adapter(cast("str", parsed.source)), cast("str", parsed.law_id))
        elif command == "dump":
            _cmd_dump(
                build_adapter(cast("str", parsed.source)),
                _read_ids(cast("str | None", parsed.ids_from), cast("list[str]", parsed.law_ids)),
                cast("str | None", parsed.out),
            )
    except (ValueError, RuntimeError, LookupError, TypeError) as exc:
        parser.exit(2, f"open-law: error: {exc}\n")


if __name__ == "__main__":
    main()
