"""Guardrailed LLM classifier for announcement subjects (plan v2 section 12.1).

Guardrails per the house LLM rules:
- input: subjects truncated to 500 chars, batched, no user-controlled text
  reaches the system prompt;
- output: pydantic-validated JSON, one retry on parse failure, then the
  deterministic fallback (other/neutral) — the pipeline never blocks on the
  provider;
- cost: temperature 0, max_tokens bounded, cache keyed by subject hash so a
  corpus is classified once; every call logged to an audit JSONL.

Provider: any OpenAI-compatible chat endpoint; default Groq. The API key
comes from the GROQ_API_KEY environment variable — absent key means the
classifier refuses to construct, and callers fall back to rules.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Final

import httpx
from pydantic import BaseModel, Field, ValidationError

from artha.events.taxonomy import CATEGORIES, EventLabel, classify_rule_based

GROQ_URL: Final = "https://api.groq.com/openai/v1/chat/completions"
MODEL: Final = "llama-3.3-70b-versatile"
MAX_SUBJECT_CHARS: Final = 500
MAX_TOKENS: Final = 120

_SYSTEM_PROMPT: Final = (
    "You classify Indian stock-exchange corporate announcements. "
    "Reply with ONLY a JSON object: "
    '{"category": <one of ' + ", ".join(CATEGORIES) + ">, "
    '"direction": -1|0|1, "materiality": 0|1|2}. '
    "direction is the presumed price impact, materiality 2 means major."
)


class _LabelSchema(BaseModel):
    category: str = Field(pattern="|".join(CATEGORIES))
    direction: int = Field(ge=-1, le=1)
    materiality: int = Field(ge=0, le=2)


class LlmClassifier:
    def __init__(self, cache_path: Path, audit_path: Path) -> None:
        key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            raise RuntimeError("GROQ_API_KEY not set; use classify_rule_based instead")
        self._key = key
        self.cache_path = cache_path
        self.audit_path = audit_path
        self._cache: dict[str, EventLabel] = {}
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                self._cache[rec["hash"]] = EventLabel(
                    rec["category"], rec["direction"], rec["materiality"]
                )

    def classify(self, subject: str) -> EventLabel:
        text = subject[:MAX_SUBJECT_CHARS]
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest in self._cache:
            return self._cache[digest]
        label = self._call_with_retry(text)
        self._cache[digest] = label
        with self.cache_path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "hash": digest,
                        "category": label.category,
                        "direction": label.direction,
                        "materiality": label.materiality,
                    }
                )
                + "\n"
            )
        return label

    def _call_with_retry(self, text: str) -> EventLabel:
        for attempt in (1, 2):
            try:
                raw = self._call(text)
                parsed = _LabelSchema.model_validate_json(raw)
                self._audit(text, raw, "ok")
                return EventLabel(parsed.category, parsed.direction, parsed.materiality)
            except (httpx.HTTPError, ValidationError, KeyError, json.JSONDecodeError) as exc:
                self._audit(text, str(exc), f"fail_attempt_{attempt}")
        return classify_rule_based(text)  # deterministic fallback, never blocks

    def _call(self, text: str) -> str:
        resp = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": MODEL,
                "temperature": 0,
                "max_tokens": MAX_TOKENS,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"]["content"])

    def _audit(self, text: str, response: str, status: str) -> None:
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"subject": text, "response": response, "status": status}) + "\n")
