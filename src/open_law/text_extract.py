"""Plain-text extraction for fetched law pages.

:func:`html_to_text` reduces a fetched HTML page to readable text with
the standard library only: scripts, styles, and comments are dropped,
tags are stripped, entities are unescaped, and whitespace is collapsed.
:func:`xml_to_text` pulls the character data out of an XML document
(legislation APIs ship the statute text inside the XML tree). PDFs are
deliberately unsupported — extracting them needs a third-party parser,
and :meth:`open_law.sources.SourceAdapter.fetch` sources that only ship
PDFs report that themselves.
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


def html_to_text(page: str) -> str:
    """Readable plain text of an HTML page (site chrome included)."""
    text = _NOISE_RE.sub(" ", page)
    text = _COMMENT_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def xml_to_text(xml: str) -> str:
    """Concatenated character data of an XML document (any namespaces)."""
    try:
        root = fromstring(xml)
    except ET.ParseError:
        return ""
    return re.sub(r"\s+", " ", " ".join(root.itertext())).strip()
