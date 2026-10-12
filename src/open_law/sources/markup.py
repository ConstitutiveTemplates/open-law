"""HTML markup cleanup shared by the source adapters.

Adapters scrape index pages and search listings that are HTML even
when the law text itself arrives as XML: titles sit inside ``<a>``
or ``<h1>`` tags, detail tables mix labels and values, and GII
(Gesetze-im-Internet) buries titles in ``htdig-keywords`` meta tags
with entities. The two helpers below separate the two intents:

- :func:`strip_markup`: entity-aware label cleanup (tags vanish without
  a trace, ``<strong>x</strong>`` → ``x``);
- :func:`collapse_markup`: table/fragment text extraction (tags become
  word separators, whitespace collapses).
"""

from __future__ import annotations

import html as _html_module
import re

__all__ = ["collapse_markup", "strip_markup"]

_TAG_RE = re.compile(r"<[^>]+>")


def strip_markup(text: str | None, *, unescape: bool = False) -> str | None:
    """Tag-stripped *text*, or None when empty/absent.

    Tags are removed without a replacement (``<strong>x</strong>`` →
    ``x``); with ``unescape=True`` entities resolve first (the GII
    ``htdig-keywords`` meta path).
    """
    if text is None:
        return None
    if unescape:
        text = _html_module.unescape(text)
    clean = _TAG_RE.sub("", text).strip()
    return clean or None


def collapse_markup(markup: str) -> str:
    """*markup* with tags replaced by spaces and whitespace collapsed."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", markup)).strip()
