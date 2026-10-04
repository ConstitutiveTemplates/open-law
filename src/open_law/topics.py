"""Subject-matter classification for fetched laws.

Comparative work needs to know *what a law is about* before any
cross-country question ("which country has no data-protection statute?")
makes sense. :func:`classify` tags a law with topics from a taxonomy of
multilingual keywords — matched case-insensitively; CJK and other
non-Latin keywords match as substrings (no word boundaries), Latin
keywords as whole words.

**The taxonomy is expert knowledge, and it lives outside the code.**
:data:`DEFAULT_TOPICS` is the built-in starter; domain experts replace
or extend it by editing a JSON file (export the starter with
``open-law taxonomy --export``) and passing it via ``--taxonomy``.
Every classification is then traceable to a keyword an expert wrote.
LLM-assisted classification over the same file format is the planned
second stage — the file, not a model, stays the interface.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import cast

__all__ = ["DEFAULT_TOPICS", "classify", "load_taxonomy"]

Topic = str

# topic id -> keywords. Latin keywords match on word boundaries,
# non-Latin (CJK, Devanagari, Bengali etc.) as substrings.
DEFAULT_TOPICS: dict[Topic, tuple[str, ...]] = {
    "data-protection": ("個人情報", "プライバシー", "data protection", "privacy", "personal data"),
    "ai": ("人工知能", "ai regulation", "artificial intelligence", "algorithm"),
    "banking": ("銀行", "金融機関", "बैंक", "ব্যাংক", "banking", "bank act", "banking act"),
    "securities": ("金融商品取引", "有価証券", "securities", "investment services"),
    "labor": ("労働", "労働者", "श्रम", "শ্রম", "labour", "labor", "employment", "worker"),
    "environment": ("環境", "वातावरण", "পরিবেশ", "emission", "environment", "climate", "pollution"),
    "tax": ("税", "कर", "কর", "taxation", "customs"),
    "corporate": ("会社", "商業登記", "corporate", "company", "commercial code"),
    "consumer": ("消費者", "उपभोक्ता", "consumer protection", "consumer"),
    "telecom": ("電気通信", "放送", "telecommunications", "broadcast", "spectrum"),
    "health": ("医薬", "医療", "स्वास्थ्य", "স্বাস্থ্য", "health", "pharmaceutical", "medicine"),
    "education": ("教育", "शिक्षा", "শিক্ষা", "education", "school"),
    "energy": ("エネルギー", "電気", "ऊर्जा", "বিদ্যুৎ", "energy", "electricity", "renewable"),
    "ip": ("特許", "著作権", "商標", "patent", "copyright", "trademark", "intellectual property"),
    "criminal": ("刑法", "刑事", "फौजदारी", "ফৌজদারি", "criminal", "penal code", "offences"),
}


def load_taxonomy(path: str | None) -> dict[Topic, tuple[str, ...]]:
    """Load the classification taxonomy.

    ``None`` returns :data:`DEFAULT_TOPICS`. Otherwise *path* is a JSON
    file mapping topic ids to keyword lists — a **complete replacement**
    of the built-in taxonomy, so experts own exactly what classifies.
    Raises ``ValueError`` with the offending topic id on any structural
    problem (wrong shapes, empty keyword lists, duplicate keywords are
    tolerated).
    """
    if path is None:
        return DEFAULT_TOPICS
    try:
        with pathlib.Path(path).open(encoding="utf-8") as taxonomy_file:
            decoded = cast("object", json.load(taxonomy_file))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"taxonomy file {path!r} is unreadable: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(decoded, dict) or not decoded:
        msg = f"taxonomy file {path!r} must be a non-empty JSON object of topic ids"
        raise ValueError(msg)
    taxonomy: dict[Topic, tuple[str, ...]] = {}
    for topic_id, keywords in cast("dict[str, object]", decoded).items():
        if not isinstance(keywords, list) or not keywords:
            msg = f"taxonomy topic {topic_id!r} must map to a non-empty keyword list"
            raise ValueError(msg)
        keywords_list = cast("list[object]", keywords)
        if any(not isinstance(keyword, str) or not keyword.strip() for keyword in keywords_list):
            msg = f"taxonomy topic {topic_id!r} has an empty or non-string keyword"
            raise ValueError(msg)
        taxonomy[topic_id] = tuple(cast("list[str]", keywords_list))
    return taxonomy


def export_taxonomy_json(topics: dict[Topic, tuple[str, ...]]) -> str:
    """Serialize *topics* as the JSON schema :func:`load_taxonomy` reads."""
    return (
        json.dumps(
            {topic: list(keywords) for topic, keywords in sorted(topics.items())},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Case-insensitive pattern for *keyword*: whole word for Latin text."""
    if keyword.isascii():
        return re.compile(rf"\b{re.escape(keyword.strip())}\b", re.IGNORECASE)
    return re.compile(re.escape(keyword), re.IGNORECASE)


def _hits(text: str, keywords: tuple[str, ...]) -> int:
    """Number of keywords found in *text*."""
    return sum(1 for keyword in keywords if _keyword_pattern(keyword).search(text))


def classify(topics: dict[Topic, tuple[str, ...]], title: str, text: str | None = None) -> tuple[Topic, ...]:
    """Topics for a law with this *title* (and optionally its full text).

    Title hits count triple — a law's subject is usually in its name.
    Returns topics with at least one hit, best first; empty when nothing
    matches (``"unclassified"`` is the caller's word for that).
    """
    scored: list[tuple[int, Topic]] = []
    for topic, keywords in topics.items():
        score = _hits(title, keywords) * 3
        if text:
            score += _hits(text, keywords)
        if score > 0:
            scored.append((score, topic))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return tuple(topic for _, topic in scored)
