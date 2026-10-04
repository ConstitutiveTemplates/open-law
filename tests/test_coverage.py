"""Coverage matrix tests."""

from __future__ import annotations

import json

from open_law.coverage import coverage_matrix
from open_law.coverage import gap_report
from open_law.topics import DEFAULT_TOPICS


def _line(jurisdiction: str, title: str) -> str:
    return json.dumps({"jurisdiction": jurisdiction, "title": title}, ensure_ascii=False)


def test_matrix_counts_laws_per_jurisdiction_and_topic() -> None:
    lines = [
        _line("JP", "銀行法"),
        _line("JP", "個人情報の保護に関する法律"),
        _line("GB", "Data Protection Act 2018"),
        _line("GB", "Data Protection (Amendment) Act"),
    ]
    matrix = coverage_matrix(lines, DEFAULT_TOPICS)
    assert matrix.jurisdictions == ("GB", "JP")
    assert matrix.counts[("JP", "banking")] == 1
    assert matrix.counts[("JP", "data-protection")] == 1
    assert matrix.counts[("GB", "data-protection")] == 2
    assert matrix.has("GB", "data-protection")
    assert not matrix.has("JP", "energy")
    assert "energy" in matrix.missing_topics("JP", DEFAULT_TOPICS)


def test_matrix_skips_malformed_and_foreign_lines() -> None:
    lines = [
        "not json",
        json.dumps(["a", "list"]),
        json.dumps({"title": "no jurisdiction"}),
        _line("JP", "労働基準法"),
        "",
    ]
    matrix = coverage_matrix(lines, DEFAULT_TOPICS)
    assert matrix.jurisdictions == ("JP",)
    assert matrix.counts[("JP", "labor")] == 1


def test_gap_report_lists_missing_topics_per_country() -> None:
    matrix = coverage_matrix([_line("GB", "Data Protection Act 2018")], DEFAULT_TOPICS)
    report = gap_report(matrix, DEFAULT_TOPICS)
    assert "GB" in report
    assert "data-protection" in report
    assert "missing" in report
    for topic in sorted(DEFAULT_TOPICS):
        assert topic in report
