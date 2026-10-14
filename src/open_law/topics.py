"""Subject-matter classification for fetched laws.

Comparative work needs to know *what a law is about* before any
cross-country question ("which country has no data-protection statute?")
makes sense. :func:`classify` tags a law with topics from a taxonomy of
multilingual keywords; :func:`classify_evidence` returns the same ranking
plus **which keyword matched**, so every classification can be traced to
a word an expert wrote.

Matching is script-aware, because the naive rules misfire badly:

- ASCII keywords match on word boundaries (``tax`` never fires inside
  ``taxidermy``).
- Keywords in scripts that delimit words with spaces — Devanagari,
  Bengali, Thaana, Lao, Hangul — must *end* a word: ``कर`` (tax) matches
  ``आयकर`` (income tax) but not ``करना`` ("to do"), which contains it.
- CJK keywords match as substrings (Han and kana do not delimit words),
  with longest-match precedence: ``電気`` (energy) no longer fires inside
  ``電気通信`` (telecommunications), while ``電気事業法`` (the Electricity
  Business Act) still counts as energy.
- A keyword shorter than two characters never matches in a law's full
  text — only in its title. In the body of a statute, a lone ``税`` says
  nothing; in a title it says everything.

**The taxonomy is expert knowledge, and it lives outside the code.**
:data:`DEFAULT_TOPICS` is the built-in starter; domain experts replace
or extend it by editing a JSON file (export the starter with
``open-law taxonomy --export``) and passing it via ``--taxonomy``.
LLM-assisted classification over the same file format is the planned
second stage — the file, not a model, stays the interface.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass
from typing import cast

__all__ = ["DEFAULT_TOPICS", "TopicMatch", "classify", "classify_evidence", "load_taxonomy"]

Topic = str

# topic id -> keywords. ASCII keywords match on whole words; keywords in
# word-delimiting scripts must end a word; CJK matches as a substring with
# longest-match precedence (see the module docstring).
DEFAULT_TOPICS: dict[Topic, tuple[str, ...]] = {
    "data-protection": (
        "個人情報",
        "プライバシー",
        "data protection",
        "privacy",
        "personal data",
        "personal information protection",  # PIPEDA-style titles
        "renseignements personnels",  # FR: PIPEDA's French short title
    ),
    "ai": ("人工知能", "ai regulation", "artificial intelligence"),
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

# Scripts whose writing systems separate words: a keyword in one of them
# must end a word, not merely appear inside a longer one. Ranges are
# (first, last) code points, used to build the regex character class.
_DELIMITING_SCRIPTS: dict[str, tuple[tuple[int, int], ...]] = {
    "devanagari": ((0x0900, 0x097F),),
    "bengali": ((0x0980, 0x09FF),),
    "thaana": ((0x0780, 0x07BF),),
    "lao": ((0x0E80, 0x0EFF),),
    "hangul": ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7A3)),
}

# A keyword this short is meaningless in a statute's body: 税, 電気 and
# कर all appear somewhere in any long text. Titles are short and
# deliberate, so they are still searched in full.
_MIN_TEXT_KEYWORD_LENGTH = 2


@dataclass(frozen=True)
class TopicMatch:
    """One topic's hit on a law, with the keywords that produced it."""

    topic: Topic
    score: int
    terms: tuple[str, ...]


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


def _script_class(keyword: str) -> str | None:
    """The regex character class of *keyword*'s script, when it delimits words."""
    code = ord(keyword[0])
    for ranges in _DELIMITING_SCRIPTS.values():
        if any(start <= code <= end for start, end in ranges):
            return "".join(rf"\u{start:04X}-\u{end:04X}" for start, end in ranges)
    return None


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Case-insensitive pattern for *keyword*, matched to its script's rules."""
    stripped = keyword.strip()
    if stripped.isascii():
        return re.compile(rf"\b{re.escape(stripped)}\b", re.IGNORECASE)
    script_class = _script_class(stripped)
    if script_class is not None:
        # Right boundary only: आयकर ends with कर and must match, while
        # करना merely contains it and must not.
        return re.compile(rf"{re.escape(stripped)}(?![{script_class}])", re.IGNORECASE)
    return re.compile(re.escape(stripped), re.IGNORECASE)


def _is_contained(
    match: tuple[int, int, Topic, str],
    matches: list[tuple[int, int, Topic, str]],
) -> bool:
    """True when *match* sits strictly inside a longer match."""
    start, end, _, _ = match
    return any(
        other_start <= start and other_end >= end and (other_end - other_start) > (end - start)
        for other_start, other_end, _, _ in matches
    )


def _matches_in(
    text: str,
    topics: dict[Topic, tuple[str, ...]],
    *,
    minimum_length: int,
) -> list[tuple[Topic, str]]:
    """(topic, keyword) for every keyword match in *text* that counts.

    The whole taxonomy is swept at once, because CJK keywords match as
    substrings and a shorter keyword nested in a longer one must lose —
    and 電気 (energy) only loses to 電気通信 (telecom) if both are visible.
    """
    matches: list[tuple[int, int, Topic, str]] = []
    for topic, keywords in topics.items():
        for keyword in keywords:
            stripped = keyword.strip()
            if len(stripped) < minimum_length:
                continue
            matches.extend(
                (found.start(), found.end(), topic, stripped) for found in _keyword_pattern(stripped).finditer(text)
            )
    kept = [match for match in matches if match[3].isascii() or not _is_contained(match, matches)]
    return [(topic, keyword) for _, _, topic, keyword in kept]


def classify_evidence(
    topics: dict[Topic, tuple[str, ...]],
    title: str,
    text: str | None = None,
) -> tuple[TopicMatch, ...]:
    """Topics for a law, each with the keywords that matched.

    Title hits count triple — a law's subject is usually in its name — and
    every returned match names the keywords behind it, so a surprising
    classification can be traced to the taxonomy entry that caused it.
    Returns topics with at least one hit, best first; empty when nothing
    matches (``"unclassified"`` is the caller's word for that).
    """
    title_matches = _matches_in(title, topics, minimum_length=1)
    text_matches = _matches_in(text, topics, minimum_length=_MIN_TEXT_KEYWORD_LENGTH) if text else []
    scored: list[TopicMatch] = []
    for topic in topics:
        title_terms = tuple(dict.fromkeys(keyword for matched, keyword in title_matches if matched == topic))
        text_terms = tuple(dict.fromkeys(keyword for matched, keyword in text_matches if matched == topic))
        score = len(title_terms) * 3 + len(text_terms)
        if score > 0:
            terms = title_terms + tuple(term for term in text_terms if term not in title_terms)
            scored.append(TopicMatch(topic=topic, score=score, terms=terms))
    scored.sort(key=lambda match: (-match.score, match.topic))
    return tuple(scored)


def classify(topics: dict[Topic, tuple[str, ...]], title: str, text: str | None = None) -> tuple[Topic, ...]:
    """Topics for a law with this *title* (and optionally its full text).

    The topic-only view of :func:`classify_evidence`.
    """
    return tuple(match.topic for match in classify_evidence(topics, title, text))
