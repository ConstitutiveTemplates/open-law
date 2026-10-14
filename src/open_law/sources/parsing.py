"""Defensive JSON/XML parsing shared by the source adapters.

Every adapter consumes an official machine channel (JSON APIs, XML
statute trees, CELLAR RDF) whose wire format drifts without notice:
nulls appear where strings were, lists hold stray scalars, payloads
arrive malformed. These helpers centralize the "parse defensively,
fail with the source's name in the message" idioms so the thirteen
adapters stay thin parsing shells over their own endpoints.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import cast

from defusedxml.ElementTree import fromstring

__all__ = [
    "as_dict",
    "as_dict_list",
    "as_dict_or_none",
    "as_str",
    "child_by_local",
    "clamp_limit",
    "decode_json",
    "pairs",
    "parse_xml",
    "xml_child_text",
    "xml_text",
]


def as_str(value: object) -> str | None:
    """Non-empty *value* stringified, else None (JSON nulls and gaps)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_dict(value: object) -> dict[str, object]:
    """*value* as a dict, or ``{}`` when it is not one (defensive JSON)."""
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def as_dict_or_none(value: object) -> dict[str, object] | None:
    """*value* as a dict when it is one, else None (defensive JSON)."""
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def as_dict_list(value: object) -> list[dict[str, object]]:
    """*value* as a list of dicts, dropping non-dict entries."""
    if not isinstance(value, list):
        return []
    return [cast("dict[str, object]", entry) for entry in cast("list[object]", value) if isinstance(entry, dict)]


def pairs(candidates: tuple[tuple[str, object], ...]) -> dict[str, str]:
    """Extras dict of the non-empty *candidates*, values stringified."""
    kept: dict[str, str] = {}
    for key, value in candidates:
        text = as_str(value)
        if text is not None:
            kept[key] = text
    return kept


def clamp_limit(limit: int) -> int:
    """A search ``limit`` clamped to at least 1."""
    return max(1, limit)


def decode_json(body: str, error: str) -> object:
    """``json.loads`` of *body*, raising ``ValueError(error)`` when malformed."""
    try:
        return cast("object", json.loads(body))
    except json.JSONDecodeError as exc:
        msg = error
        raise ValueError(msg) from exc


def parse_xml(body: str, error: str) -> ET.Element:
    """``defusedxml`` root of *body*, raising ``ValueError(error)`` when malformed."""
    try:
        return fromstring(body)
    except ET.ParseError as exc:
        msg = error
        raise ValueError(msg) from exc


def xml_text(element: ET.Element | None) -> str | None:
    """Stripped text of *element*, or None when empty/absent."""
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped or None


def xml_child_text(parent: ET.Element, tag: str) -> str | None:
    """Stripped text of *parent*'s first child named *tag*."""
    return xml_text(parent.find(tag))


def child_by_local(parent: ET.Element | None, local: str) -> ET.Element | None:
    """First child of *parent* whose tag ends with *local* (any namespace)."""
    if parent is None:
        return None
    for child in parent:
        if child.tag.rpartition("}")[2] == local:
            return child
    return None
