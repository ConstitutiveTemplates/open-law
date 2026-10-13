"""Source adapter contract: one class per jurisdiction, one interface.

Backward-compatibility shim: the contract now lives in
:mod:`open_law.sources.adapter` (:class:`SourceAdapter`,
:exc:`NotAvailableBySourceError`), markup cleanup in
:mod:`open_law.sources.markup`, and defensive JSON/XML parsing in
:mod:`open_law.sources.parsing`. This module re-exports every public
name so ``from open_law.sources.base import SourceAdapter`` (used by
all thirteen adapters, the test helpers, and third-party adapters)
keeps working unchanged.
"""

from __future__ import annotations

from open_law.sources.adapter import NotAvailableBySourceError
from open_law.sources.adapter import SourceAdapter
from open_law.sources.parsing import as_dict
from open_law.sources.parsing import as_dict_list
from open_law.sources.parsing import as_dict_or_none
from open_law.sources.parsing import as_str
from open_law.sources.parsing import child_by_local
from open_law.sources.parsing import clamp_limit
from open_law.sources.parsing import collapse_markup
from open_law.sources.parsing import decode_json
from open_law.sources.parsing import pairs
from open_law.sources.parsing import parse_xml
from open_law.sources.parsing import strip_markup
from open_law.sources.parsing import xml_child_text
from open_law.sources.parsing import xml_text

__all__ = [
    "NotAvailableBySourceError",
    "SourceAdapter",
    "as_dict",
    "as_dict_list",
    "as_dict_or_none",
    "as_str",
    "child_by_local",
    "clamp_limit",
    "collapse_markup",
    "decode_json",
    "pairs",
    "parse_xml",
    "strip_markup",
    "xml_child_text",
    "xml_text",
]
