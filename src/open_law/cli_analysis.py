"""Corpus-bound CLI commands: coverage/correspond/taxonomy.

These commands never touch the network: they read the JSONL corpus
written by ``open-law dump`` (a file, or ``-`` for stdin), resolve
topics through the expert taxonomy (:func:`open_law.topics.load_taxonomy`,
overlaid with :mod:`open_law.corpus` annotations), and print a matrix,
a candidate list, or the editable taxonomy schema.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import TextIO
from typing import cast

from open_law.cli_io import print_json
from open_law.corpus import iter_corpus
from open_law.corpus import load_annotations
from open_law.correspond import find_correspondences
from open_law.coverage import coverage_matrix
from open_law.coverage import gap_report
from open_law.topics import DEFAULT_TOPICS
from open_law.topics import export_taxonomy_json
from open_law.topics import load_taxonomy

__all__ = ["run_analysis_commands"]


def open_corpus(corpus_path: str) -> TextIO:
    """An open handle on a dumped corpus file, or stdin for '-' (never closed)."""
    if corpus_path == "-":
        return sys.stdin
    return pathlib.Path(corpus_path).open(encoding="utf-8")


def with_annotation_topics(
    topics: dict[str, tuple[str, ...]], annotations: dict[str, tuple[str, ...]] | None
) -> dict[str, tuple[str, ...]]:
    """The taxonomy overlaid with expert annotations (annotation topics added)."""
    all_topics = dict(topics)
    if annotations:
        for annotated in annotations.values():
            for topic in annotated:
                all_topics.setdefault(topic, (topic,))
    return all_topics


def cmd_coverage(
    corpus_path: str,
    *,
    as_json: bool,
    taxonomy_path: str | None,
    annotations_path: str | None,
) -> None:
    """Print the country-by-topic coverage matrix for a dumped corpus."""
    topics = load_taxonomy(taxonomy_path)
    annotations = load_annotations(annotations_path) if annotations_path else None
    all_topics = with_annotation_topics(topics, annotations)
    corpus = open_corpus(corpus_path)
    try:
        matrix = coverage_matrix(corpus, topics, annotations)
    finally:
        if corpus is not sys.stdin:
            corpus.close()
    if as_json:
        print_json(
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


def cmd_correspond(
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
    corpus = open_corpus(corpus_path)
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
    print(
        "candidates for human review — a candidate is not an equivalence; "
        "similarity is title-based and only computed within one language "
        "(bridge = scored through an English translation, topic+era = unscored)"
    )
    for candidate in candidates:
        similarity = f"{candidate.similarity:.3f}" if candidate.similarity is not None else "  n/a"
        print(
            f"{similarity}  [{candidate.topic}] {candidate.basis}  "
            f"{candidate.jurisdiction_a} {candidate.year_a or ''} {candidate.title_a!r}"
            f" (matched: {', '.join(candidate.terms_a) or 'expert annotation'})"
            f"  <->  "
            f"{candidate.jurisdiction_b} {candidate.year_b or ''} {candidate.title_b!r}"
            f" (matched: {', '.join(candidate.terms_b) or 'expert annotation'})"
        )


def cmd_taxonomy(export_path: str | None) -> None:
    """Export the built-in taxonomy as the expert-editable JSON schema."""
    if export_path is None or export_path == "-":
        sys.stdout.write(export_taxonomy_json(DEFAULT_TOPICS))
    else:
        pathlib.Path(export_path).write_text(export_taxonomy_json(DEFAULT_TOPICS), encoding="utf-8")


def run_analysis_commands(command: str, parsed: argparse.Namespace) -> None:
    """Dispatch the corpus-analysis subcommands (coverage/correspond/taxonomy)."""
    if command == "coverage":
        cmd_coverage(
            cast("str", parsed.corpus),
            as_json=cast("bool", parsed.json),
            taxonomy_path=cast("str | None", parsed.taxonomy),
            annotations_path=cast("str | None", parsed.annotations),
        )
    elif command == "correspond":
        cmd_correspond(
            cast("str", parsed.corpus),
            taxonomy_path=cast("str | None", parsed.taxonomy),
            annotations_path=cast("str | None", parsed.annotations),
            min_similarity=cast("float", parsed.min_similarity),
            year_window=cast("int", parsed.year_window),
        )
    elif command == "taxonomy":
        cmd_taxonomy(cast("str | None", parsed.export))
