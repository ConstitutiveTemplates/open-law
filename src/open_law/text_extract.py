"""Plain-text extraction for fetched law pages.

:func:`html_to_text` reduces a fetched HTML page to readable text with
the standard library only: scripts, styles, and comments are dropped,
tags are stripped, entities are unescaped, and whitespace is collapsed.
:func:`xml_to_text` pulls the character data out of an XML document
(legislation APIs ship the statute text inside the XML tree). PDFs are
deliberately unsupported — extracting them needs a third-party parser,
and :meth:`open_law.sources.SourceAdapter.fetch` sources that only ship
PDFs report that themselves.

``preserve_structure`` keeps paragraph and section breaks when ``True``:
HTML gets ``\\n\\n`` between block elements, ``#``-prefixed headings for
``h1``-``h4``, and line-broken lists; XML gets a newline per element
boundary so section/article separation survives. Default stays lossy
(single-space collapse) for backwards compatibility.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from defusedxml.ElementTree import fromstring

__all__ = ["html_to_text", "xml_to_text"]

_NOISE_RE = re.compile(r"<(script|style|head|noscript)\b[^>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(
    r"</?(p|div|section|article|header|footer|blockquote|pre|tr|table|thead|tbody|tfoot|ul|ol|dl|dd|dt)\b[^>]*>",
    re.IGNORECASE,
)
_HR_RE = re.compile(r"<hr\b[^>]*>", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LI_CLOSE_RE = re.compile(r"</li\s*>", re.IGNORECASE)
_LI_OPEN_RE = re.compile(r"<li\b[^>]*>", re.IGNORECASE)
_H56_RE = re.compile(r"</?h[5-6]\b[^>]*>", re.IGNORECASE)


def _strip_noise(page: str) -> str:
    """*page* without scripts/styles/head/noscript blocks and comments."""
    text = _NOISE_RE.sub(" ", page)
    return _COMMENT_RE.sub(" ", text)


def _collapse_flat(text: str) -> str:
    """Lossy single-space collapse of tag-stripped *text*."""
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _mark_headings(text: str) -> str:
    """Markdown headings for h1-h4, plain paragraph breaks for h5-h6."""
    for lvl in (1, 2, 3, 4):
        text = re.sub(rf"<h{lvl}\b[^>]*>", f"\n\n{'#' * lvl} ", text, flags=re.IGNORECASE)
        text = re.sub(rf"</h{lvl}\s*>", "\n\n", text, flags=re.IGNORECASE)
    # remaining h5-h6 as plain blocks
    return _H56_RE.sub("\n\n", text)


def _mark_lists_and_blocks(text: str) -> str:
    """Line-broken list items and paragraph breaks for block elements."""
    # lists: <li> -> newline + dash, </li> removed
    text = _LI_OPEN_RE.sub("\n- ", text)
    text = _LI_CLOSE_RE.sub("", text)
    # block elements -> double newline
    text = _BLOCK_RE.sub("\n\n", text)
    return _HR_RE.sub("\n\n", text)


def _insert_block_breaks(text: str) -> str:
    """Newline structure for breaks, headings, lists and block elements."""
    # <br> -> single newline
    text = _BR_RE.sub("\n", text)
    text = _mark_headings(text)
    return _mark_lists_and_blocks(text)


def _normalise_lines(text: str) -> str:
    """Per-line horizontal-whitespace cleanup, keeping paragraph breaks."""
    text = html.unescape(text)
    # normalize horizontal whitespace per line, but preserve newlines
    lines = text.split("\n")
    cleaned = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in lines]
    # collapse consecutive empty lines to a single paragraph break
    parts: list[str] = []
    prev_empty = False
    for ln in cleaned:
        if ln == "":
            if not prev_empty:
                parts.append("")
            prev_empty = True
        else:
            parts.append(ln)
            prev_empty = False
    joined = "\n".join(parts)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def html_to_text(page: str, preserve_structure: bool = False) -> str:  # noqa: FBT001,FBT002
    """Readable plain text of an HTML page (site chrome included)."""
    if not preserve_structure:
        return _collapse_flat(_strip_noise(page))
    # Structural mode: keep paragraphs, headings and lists.
    structured = _insert_block_breaks(_strip_noise(page))
    # strip remaining inline tags
    return _normalise_lines(_TAG_RE.sub(" ", structured))


def _parse_xml(xml: str) -> ET.Element | None:
    """Root element of *xml*, or None when it does not parse."""
    try:
        return fromstring(xml)
    except ET.ParseError:
        return None


def xml_to_text(xml: str, preserve_structure: bool = False) -> str:  # noqa: FBT001,FBT002
    """Concatenated character data of an XML document (any namespaces)."""
    root = _parse_xml(xml)
    if root is None:
        return ""
    if not preserve_structure:
        return re.sub(r"\s+", " ", " ".join(root.itertext())).strip()
    # Structural: newline at element boundaries.
    pieces = [re.sub(r"\s+", " ", t.strip()) for t in root.itertext() if t is not None and t.strip()]
    return "\n".join(pieces)
