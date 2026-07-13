"""Announcement taxonomy (plan v2 section 12.1).

Two classifiers behind one output type:

- ``classify_rule_based``: deterministic keyword rules over the subject
  line. Free, reproducible, coarse. This is the v0 the pipeline runs on.
- ``LlmClassifier`` (see ``taxonomy_llm.py``): guardrailed LLM upgrade,
  key-gated; same output schema, cached, audited, neutral fallback.

Direction is the PRESUMED price direction of the category (+1 good news,
-1 bad, 0 neutral/unknown); the event study measures the real one.
Materiality: 0 routine, 1 notable, 2 major.
"""

import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class EventLabel:
    category: str
    direction: int
    materiality: int


CATEGORIES: Final = (
    "earnings_result",
    "order_win",
    "capex_expansion",
    "pledge",
    "rating_action",
    "m_and_a",
    "fundraising",
    "litigation_regulatory",
    "board_change",
    "dividend_distribution",
    "other",
)

# Ordered: first match wins. Patterns run on the lowercased subject.
_RULES: Final[list[tuple[str, str, int, int]]] = [
    (
        r"financial result|unaudited.*result|audited.*result|results for the quarter",
        "earnings_result",
        0,
        2,
    ),
    (
        r"\border(s)? (win|won|received|book|bagged)|bagging|contract (award|won|received)",
        "order_win",
        1,
        1,
    ),
    (r"capacity expansion|capex|commissioning|new (plant|facility|unit)", "capex_expansion", 1, 1),
    (r"pledge", "pledge", -1, 1),
    (
        r"credit rating|rating.*(upgrade|downgrade|reaffirm|revised)|icra|crisil|care ratings",
        "rating_action",
        0,
        1,
    ),
    (
        r"amalgamation|merger|acquisition|acquire|demerger|scheme of arrangement|takeover",
        "m_and_a",
        0,
        2,
    ),
    (
        r"rights issue|qip|preferential (issue|allotment)|fund.?raising"
        r"|raising of funds|ncd|commercial paper",
        "fundraising",
        0,
        1,
    ),
    (
        r"litigation|penalty|show cause|sebi order|investigation"
        r"|search and seizure|insolvency|nclt",
        "litigation_regulatory",
        -1,
        2,
    ),
    (
        r"resignation|appointment|cessation|change in (director|management|kmp)|key managerial",
        "board_change",
        0,
        0,
    ),
    (r"dividend|buyback|buy-back|bonus issue|stock split", "dividend_distribution", 1, 1),
]

_COMPILED: Final = [(re.compile(p, re.IGNORECASE), c, d, m) for p, c, d, m in _RULES]


def classify_rule_based(subject: str | None) -> EventLabel:
    if subject:
        for pattern, category, direction, materiality in _COMPILED:
            if pattern.search(subject):
                return EventLabel(category, direction, materiality)
    return EventLabel("other", 0, 0)
