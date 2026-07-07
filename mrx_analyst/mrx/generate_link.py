"""
MRX Link Generator — LLM-as-Planner Architecture, for the Multirow Risk
Snapshot view (viewid=6168).

The LLM reasons about the user's intent and builds the complete MRX URL
for this one view directly, guided by manual.md and the tables/ reference
data alongside this file. A different MRX view would get its own sibling
module under mrx/views/, with its own manual + tables — this file (and
validation.py next to it) is intentionally Multirow-only, not generic.
"""

from pathlib import Path
from functools import lru_cache
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

from .models import MRXPlan

# =============================================================================
# UTILITIES
# =============================================================================

# Resolve resources relative to THIS file, not the process CWD, so the loader
# works no matter where the app is launched from.
BASE_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "2_mrx" / "manuals"
MANUAL_PATH = BASE_DIR / "multirow.md"
TABLES_DIR = BASE_DIR / "tables"

# The reference tables, in the order they are appended to the system prompt.
# The manual refers to each of these by filename, so they must all be present.
TABLE_FILES = [
    "multirow_parameters.md",
    "risk_type_selection.md",
    "row_selection.md",
    "columns_selection.md",
]


# These read static files that never change at runtime, but get_link() calls
# build_system_prompt() on every planning attempt — including every retry in
# _plan_and_validate's self-correction loop, and once per view in a
# multi-fetch question. Without caching, a 3-view question with one retry
# each re-reads and re-parses the manual + 4 tables roughly a dozen times
# for content that's identical every time. lru_cache(maxsize=1) is safe
# here specifically because these are pure functions of on-disk files that
# this process never modifies (they're read-only reference material).


@lru_cache(maxsize=1)
def load_manual() -> str:
    """Load the MRX Multirow manual (the LLM's instructions)."""
    if MANUAL_PATH.exists():
        return MANUAL_PATH.read_text(encoding="utf-8")
    raise FileNotFoundError(f"MRX manual not found at {MANUAL_PATH}")


@lru_cache(maxsize=1)
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


@lru_cache(maxsize=1)
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

def get_link(llm, query: str, *, prior_attempts: list[tuple[MRXPlan, str]] = ()) -> MRXPlan:
    """
    Main entry point: take a natural language query, return the structured
    plan (URL, reasoning, assumptions, confidence, SmartDF rephrasing).

    `prior_attempts` is a list of (rejected_plan, validation_error) pairs from
    earlier tries at the same query. Each is replayed as an assistant turn
    followed by the error as a correction request, so the LLM sees exactly
    what it produced and why it was rejected before trying again.
    """
    system_prompt = build_system_prompt()

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="Use a Multirow Risk Snapshot for this request: " + query),
    ]
    for prior_plan, error in prior_attempts:
        messages.append(AIMessage(content=prior_plan.model_dump_json()))
        messages.append(HumanMessage(
            content=(
                "That plan was rejected: " + error + "\n"
                "Fix the plan and return a corrected MRXPlan that addresses this "
                "specific problem. Keep everything else about the plan the same "
                "unless the fix requires changing it."
            )
        ))

    structured_llm = llm.with_structured_output(MRXPlan)
    plan: MRXPlan = structured_llm.invoke(messages)

    return plan