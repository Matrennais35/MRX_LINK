"""
MRX Link Generator — LLM-as-Planner Architecture

The LLM reasons about the user's intent, selects the right view,
and builds the complete MRX URL directly.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import pymrx
from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import SystemMessage, HumanMessage


# =============================================================================
# PYDANTIC MODEL
# =============================================================================

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


# =============================================================================
# UTILITIES
# =============================================================================

def previous_business_day(date_str: str) -> str:
    """Calculate previous business day (skip weekends)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    dt -= timedelta(days=1)
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


# Resolve resources relative to THIS file, not the process CWD, so the loader
# works no matter where the app is launched from.
BASE_DIR = Path.cwd()
MANUAL_PATH = BASE_DIR / "mrx_manual.md"
TABLES_DIR = BASE_DIR / "tables"

# The reference tables, in the order they are appended to the system prompt.
# The manual refers to each of these by filename, so they must all be present.
TABLE_FILES = [
    "multirow_parameters.md",
    "risk_type_selection.md",
    "row_selection.md",
    "columns_selection.md",
]


def load_manual() -> str:
    """Load the MRX Multirow manual (the LLM's instructions)."""
    if MANUAL_PATH.exists():
        return MANUAL_PATH.read_text(encoding="utf-8")
    raise FileNotFoundError(f"MRX manual not found at {MANUAL_PATH}")


def load_tables() -> str:
    """Load and concatenate the reference tables the manual points to.

    Each table is emitted under a clear delimiter so the model can locate the
    one a given parameter references (e.g. `risk_type_selection.md` for p13).
    """
    chunks = []
    for name in TABLE_FILES:
        path = TABLES_DIR / name
        if not path.exists():
            raise FileNotFoundError(f"MRX reference table not found at {path}")
        chunks.append(
            f"\n\n===== REFERENCE TABLE: {name} =====\n\n"
            + path.read_text(encoding="utf-8")
        )
    return "".join(chunks)


def build_system_prompt() -> str:
    """The full system context: the manual followed by every reference table."""
    return (
        load_manual()
        + "\n\n---\n\n"
        + "# Appended reference tables\n\n"
        + "The tables the manual refers to follow. Treat them as the single "
        + "source of truth for all codes and parameter values.\n"
        + load_tables()
    )


# =============================================================================
# LLM ORCHESTRATOR
# =============================================================================

def get_link(llm, query: str) -> dict:
    """
    Main entry point: take a natural language query, return a structured result
    with URL, reasoning, and assumptions.
    """
    system_prompt = build_system_prompt()

    structured_llm = llm.with_structured_output(MRXPlan)
    plan: MRXPlan = structured_llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content="Use a Multirow Risk Snapshot for this request: " + query),
    ])


    return {
        "url": plan.url,
        "parameters": plan.parameters,
        "intent": plan.intent,
        "reasoning": plan.view_reasoning,
        "assumptions": plan.assumptions,
        "confidence": plan.confidence,
        "SmartDF": plan.SmartDF
    }