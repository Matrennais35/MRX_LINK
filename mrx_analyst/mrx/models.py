"""Shared data contracts between pipeline stages, independent of any
specific MRX view.

MRXPlan's shape (intent, reasoning, confidence, url, ...) isn't specific to
any one MRX view — only the *content* a planner puts in it is. It lives in
core/, not in views/, so storage and core code that types/stores/compares a
plan never imports across the views boundary (which would drag pymrx into
every import chain).
"""

from typing import Optional

from pydantic import BaseModel, Field


class MRXPlan(BaseModel):
    """LLM output: reasoning + the complete MRX URL."""

    # Reasoning (shown to user)
    intent: str = Field(description="One sentence: what does the user want to see?")
    view_reasoning: str = Field(description="Why this view was chosen")
    parameters: str = Field(description="What did you input as parameters in the MRX view")
    assumptions: list[str] = Field(default_factory=list, description="All assumptions made")
    confidence: float = Field(ge=0.0, le=1.0, description="How confident in this plan (0-1)")
    needs_clarification: Optional[str] = Field(None, description="Question to ask user if unsure")
    SmartDF: str = Field(description="The question re-phrased for a SmartDataframe consumer")

    # The URL — built by the LLM directly using the manual's templates
    url: str = Field(description="The complete MRX URL with all parameters")
