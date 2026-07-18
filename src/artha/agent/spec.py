"""Feature proposal schema for the research agent (Track B B6).

Every proposal — LLM-generated or seed — is validated here before any
code derived from it runs. The expression is a string in the restricted
DSL enforced by :mod:`artha.agent.sandbox`; this schema only bounds its
size and shape.
"""

from pydantic import BaseModel, Field


class FeatureProposal(BaseModel):
    """One candidate cross-sectional feature."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,30}$")
    rationale: str = Field(min_length=1, max_length=500)
    expression: str = Field(min_length=1, max_length=300)
    lookback_days: int = Field(ge=1, le=252)
