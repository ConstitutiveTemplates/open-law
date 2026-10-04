"""Date normalization tests."""

from __future__ import annotations

import pytest

from open_law.dates import to_iso_date


@pytest.mark.parametrize(
    ("raw", "dayfirst", "expected"),
    [
        ("20250318", False, "2025-03-18"),
        ("2025-03-18", False, "2025-03-18"),
        ("2025/03/18", False, "2025-03-18"),
        ("17-10-2023", True, "2023-10-17"),
        ("17/10/2023", True, "2023-10-17"),
        ("03-18-2025", False, "2025-03-18"),
        ("2025-03-18 ", False, "2025-03-18"),
    ],
)
def test_to_iso_date_converts_declared_formats(raw: str, *, dayfirst: bool, expected: str) -> None:
    assert to_iso_date(raw, dayfirst=dayfirst) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "not a date", "32-13-2025"])
def test_to_iso_date_returns_none_for_unparsable(raw: str | None) -> None:
    assert to_iso_date(raw) is None


def test_ambiguous_day_month_requires_declared_order() -> None:
    """Without dayfirst, dashed dates read month-first (US convention)."""
    assert to_iso_date("05-06-2024", dayfirst=True) == "2024-06-05"
    assert to_iso_date("05-06-2024", dayfirst=False) == "2024-05-06"
