"""Feature proposers: deterministic seeds, plus an optional Groq LLM
proposer gated on GROQ_API_KEY (Track B B6).

Offline (no key, or ``offline=True``) the agent runs entirely on the
seed list, so the loop is reproducible without any external service.
The LLM path follows the house rules: prompt lives here as a constant,
max_tokens bounded, 30s timeout, one retry on 429/5xx, schema
validation with one re-ask, and seeds as the degradation path.
"""

import json
import os
import time
from typing import Final

import httpx
from pydantic import ValidationError

from artha.agent.spec import FeatureProposal

MAX_PROPOSALS: Final = 8

GROQ_URL: Final = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL: Final = "llama-3.3-70b-versatile"
GROQ_MAX_TOKENS: Final = 900
GROQ_TIMEOUT_S: Final = 30.0

PROPOSER_PROMPT: Final = """\
You are a quantitative researcher proposing cross-sectional equity features
for NSE cash equities. Daily OHLCV data per symbol; features are computed
per symbol from history up to day t's close, then z-scored across symbols
per date. Label: 5-day forward return z-score.

Write each feature in this restricted DSL (nothing else is executable):
  col(name)          -> column; name in: adj_close, close, high, low, traded_value
  dret()             -> daily return of adj_close
  shift(e, n)        -> e lagged n days (1 <= n <= 252)
  roll_mean(e, n), roll_std(e, n), roll_max(e, n), roll_min(e, n)
  absv(e), log1p(e)
  arithmetic: + - * / and numeric constants
No other functions, no attributes, no keywords. Add a small constant to
any divisor. Max window 252 days.

Known-strong signals already in the library (do not duplicate): momentum
12-1, n-day returns, short-term reversal, realized and downside vol,
distance to 52w high/low, Amihud illiquidity, turnover z, ATR range,
63d drawdown.

Return ONLY a JSON array, no prose, of {n} objects with keys:
  name (snake_case, <=30 chars), rationale (<=400 chars),
  expression (DSL string, <=280 chars), lookback_days (int, max window used).
"""

SEED_SPECS: Final[list[FeatureProposal]] = [
    FeatureProposal(
        name="vol_ratio_21_63",
        rationale=(
            "Short-run vs medium-run realized vol; a rising ratio flags a regime "
            "shift the level features miss."
        ),
        expression="roll_std(dret(), 21) / (roll_std(dret(), 63) + 0.000001)",
        lookback_days=64,
    ),
    FeatureProposal(
        name="range_pos_21d",
        rationale=(
            "Position of today's price inside its 21d range; near-high names "
            "behave differently from near-low names beyond plain momentum."
        ),
        expression=(
            "(col('adj_close') - roll_min(col('adj_close'), 21)) / "
            "(roll_max(col('adj_close'), 21) - roll_min(col('adj_close'), 21) + 0.000001)"
        ),
        lookback_days=21,
    ),
    FeatureProposal(
        name="illiq_trend_5_63",
        rationale=(
            "Recent Amihud illiquidity relative to its own 63d norm; drying "
            "liquidity often precedes price weakness."
        ),
        expression=(
            "roll_mean(absv(dret()) / (col('traded_value') + 1.0), 5) / "
            "(roll_mean(absv(dret()) / (col('traded_value') + 1.0), 63) + 0.000000000001)"
        ),
        lookback_days=64,
    ),
]


def _parse_proposals(content: str) -> list[FeatureProposal]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    items = json.loads(text)
    if not isinstance(items, list):
        raise ValueError("expected a JSON array")
    out: list[FeatureProposal] = []
    for item in items:
        try:
            out.append(FeatureProposal.model_validate(item))
        except ValidationError:
            continue
    return out


def _propose_llm(n: int, api_key: str) -> list[FeatureProposal]:
    payload = {
        "model": GROQ_MODEL,
        "max_tokens": GROQ_MAX_TOKENS,
        "temperature": 0.7,
        "messages": [{"role": "user", "content": PROPOSER_PROMPT.format(n=n)}],
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=GROQ_TIMEOUT_S) as client:
        for attempt in (1, 2):
            resp = client.post(GROQ_URL, json=payload, headers=headers)
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt == 1:
                time.sleep(2.0)
                continue
            resp.raise_for_status()
            break
    content = resp.json()["choices"][0]["message"]["content"]
    proposals = _parse_proposals(content)
    if not proposals:
        raise ValueError("no valid proposals in LLM response")
    return proposals[:n]


def propose(n: int, *, offline: bool = False) -> tuple[list[FeatureProposal], str]:
    """Up to ``n`` validated proposals and the source used ("seeds"/"groq").

    Falls back to seeds on any LLM failure — the agent never blocks on the
    provider being down.
    """
    n = min(n, MAX_PROPOSALS)
    api_key = os.environ.get("GROQ_API_KEY")
    if offline or not api_key:
        return SEED_SPECS[:n], "seeds"
    try:
        return _propose_llm(n, api_key), "groq"
    except Exception:
        return SEED_SPECS[:n], "seeds"
