"""The per-step decision: the LLM call that drives the controller loop.

Rather than classifying the whole question up front, once, before any data
is seen, the pipeline decides one step at a time, *after* seeing what
each fetch returned: "I have enough — answer now" or "I need this specific
additional cut — fetch it." That after-seeing-data property is the whole
point (see docs/agent_loop_design.md); it's what lets a drill-down pick its
next fetch based on the previous fetch's result instead of guessing the
full shape blind.

This mirrors the existing structured-output pattern exactly (`MRXPlan`): a Pydantic schema + a system prompt +
`llm.with_structured_output(...)`. No new LLM-calling mechanism.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage


class StepDecision(BaseModel):
    """One iteration's decision. `reasoning` is persisted per step for the
    audit trail (the "why each fetch happened" chain) AND threaded into the
    answer prompt as per-frame provenance — the same field used twice (see
    docs/agent_loop_design.md, resolved open-question #4).
    """

    action: Literal["fetch", "answer"]
    reasoning: str = Field(
        description="Why this action — what the gathered data does or doesn't yet show. "
        "Recorded for audit and shown to the user."
    )
    fetch_query: str = Field(
        default="",
        description="When action=='fetch': the natural-language sub-question to fetch next, "
        "e.g. 'FX Vega for DESK_A broken down by deal'. Fed to the existing "
        "plan->validate->fetch pipeline unchanged. Empty when action=='answer'.",
    )


SYSTEM_PROMPT = """\
You are driving a market-risk data investigation one step at a time. At each
step you decide whether the data gathered so far is enough to answer the
user's question, or whether one more specific MRX fetch is needed first.

You are given:
- The user's original question.
- A summary of the data already available to answer it (each dataset's
  description, columns, and a small sample) — NOT the full data. This
  includes both data fetched earlier in THIS investigation AND data fetched
  for EARLIER questions in the same conversation (labelled "from an earlier
  question"). Both are equally usable — a follow-up like "plot the variation"
  or "which desk drove that" can almost always be answered from data an
  earlier question already fetched, with NO new fetch.

Choose exactly one action:
- "answer": the available data is sufficient to answer the question now.
  Leave fetch_query empty. STRONGLY prefer this whenever the existing data
  (including earlier-question data) already contains what the question needs
  — every fetch is a slow, costly call into a production risk system, and a
  follow-up that re-plots or re-analyses existing data must NOT trigger one.
- "fetch": the available data genuinely cannot answer the question — it needs
  a different date range, risk type, node, or breakdown that nothing already
  fetched contains. Put that ONE next fetch as a natural-language
  sub-question in fetch_query. Ask for exactly one thing — you'll get another
  turn to decide after you see its result.

Always give a concrete `reasoning`: what the available data does or does not
show, and why that leads to this action. This reasoning is shown to the
analyst and kept as an audit record of how the answer was reached.

If NO data is available at all (this is the first question and nothing has
been fetched), you must "fetch" — there is nothing to answer from. Put the
fetch that best begins answering the question (often the question itself) as
fetch_query.
"""


def _describe_gathered(gathered) -> str:
    """A compact, prompt-safe summary of the datasets gathered so far —
    each one's description, columns, and a small sample. Deliberately not
    the full data (same stance as smart_pandas._describe_df): the model
    decides the NEXT step from shape and a glance at values, not by
    re-reading every row.

    `gathered` is a list of (label, df) pairs — the loop's accumulated
    ViewResults, already reduced to what this prompt needs. Empty list =>
    first step, nothing fetched yet.
    """
    if not gathered:
        return "(nothing fetched yet — this is the first step)"
    chunks = []
    for label, df in gathered:
        columns = ", ".join(df.columns)
        sample = df.head(3).to_string()
        chunks.append(f"- {label}\n  columns: {columns}\n  sample:\n{sample}")
    return "\n\n".join(chunks)


def decide_next_step(llm, query: str, gathered) -> StepDecision:
    """Ask the LLM whether to fetch once more or answer now, given the
    original `query` and the data `gathered` so far (a list of (label, df)
    pairs; empty on the first step).

    Same structured-output mechanism as get_link — just a different schema
    and prompt. The loop (see loop.py) is what enforces the
    hard fetch cap and runs every resulting fetch through the existing
    validation gate; this call only proposes the next action, it never
    executes one.
    """
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=(
            f"User's question: {query}\n\n"
            f"Data gathered so far:\n{_describe_gathered(gathered)}"
        )),
    ]
    structured_llm = llm.with_structured_output(StepDecision)
    return structured_llm.invoke(messages)
