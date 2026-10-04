"""JSONL consolidation tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from open_law.dataset import dump_jsonl
from open_law.models import Law, LawSummary


def test_dump_jsonl_writes_one_object_per_line(tmp_path: Path) -> None:
    laws = [
        Law(
            source="bd",
            jurisdiction="BD",
            law_id="43",
            title="The Kazis Act, 1880",
            extras=(("year", "1880"),),
        ),
        LawSummary(source="jp", jurisdiction="JP", law_id="1", title="銀行法"),
    ]
    out = tmp_path / "laws.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        written = dump_jsonl(laws, fh)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert written == 2
    assert len(lines) == 2
    first, second = (cast("dict[str, object]", json.loads(line)) for line in lines)
    assert first["title"] == "The Kazis Act, 1880"
    assert first["extras"] == [["year", "1880"]]
    # non-ASCII stays unescaped, as promised by ensure_ascii=False
    assert second["title"] == "銀行法"


def test_dump_jsonl_empty_input_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "laws.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        assert dump_jsonl([], fh) == 0
    assert out.read_text(encoding="utf-8") == ""
