"""JSONL consolidation for fetched laws.

The "consolidate" half of the mission: adapters fetch one law at a
time; :func:`dump_jsonl` lines them up as JSONL — one JSON object per
line, non-ASCII kept as-is — so batches land in a single
append-friendly file that notebooks, DuckDB, or jq consume directly.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from typing import TextIO

from open_law.models import LawSummary

__all__ = ["dump_jsonl"]


def dump_jsonl(laws: Iterable[LawSummary], out: TextIO) -> int:
    """Write *laws* to *out* as JSONL and return the count written.

    Accepts both :class:`Law` and the lighter :class:`LawSummary` —
    search results consolidate as readily as fetched documents.
    """
    count = 0
    for law in laws:
        out.write(json.dumps(asdict(law), ensure_ascii=False) + "\n")
        count += 1
    return count
