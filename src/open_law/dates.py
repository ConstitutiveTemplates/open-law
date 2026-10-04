"""Date normalization for adapter-parsed dates.

Sources print dates in their own conventions (Korea's ``YYYYMMDD``,
Laos's ``DD-MM-YYYY``). :func:`to_iso_date` converts mechanically to
ISO-8601 for the model's ``promulgation_date`` while the raw string
stays in ``extras``. The caller declares the source's day/month order
(``dayfirst``) — the function never guesses an ambiguous order on its
own. Anything unparsable returns ``None``; adapters decide whether
that is fatal.
"""

from __future__ import annotations

from datetime import datetime

__all__ = ["to_iso_date"]


def _formats(*, dayfirst: bool) -> tuple[str, ...]:
    """Accepted layouts, ordered; *dayfirst* picks the D/M-Y interpretation."""
    year_first = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d")
    day_first = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y")
    month_first = ("%m-%d-%Y", "%m/%d/%Y")
    return year_first + (day_first if dayfirst else month_first + day_first)


def to_iso_date(raw: str | None, *, dayfirst: bool = False) -> str | None:
    """Convert *raw* to ISO-8601 when it parses under the declared order.

    ``to_iso_date("20250318")`` → ``"2025-03-18"``;
    ``to_iso_date("17-10-2023", dayfirst=True)`` → ``"2023-10-17"``.
    Returns ``None`` for empty or unparsable input.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    for fmt in _formats(dayfirst=dayfirst):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None
