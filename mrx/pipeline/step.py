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
    audit trail (the "why" chain) AND, for an analyze step, threaded into the
    answer prompt as per-frame provenance (see docs/agent_loop_design.md).

    `action` is the crux: the orchestrator decides not just *whether* to fetch,
    but *how to answer* — running the data pipeline only when the question
    genuinely needs it, and otherwise answering directly in prose. Data work is
    one option, not the mandatory path.
    """

    action: Literal["fetch", "analyze", "respond"]
    reasoning: str = Field(
        description="Why this action — what the question needs and what the available data does "
        "or doesn't show. Recorded for audit and shown to the user."
    )
    fetch_query: str = Field(
        default="",
        description="ONLY when action=='fetch': the natural-language sub-question to fetch next, "
        "e.g. 'FX Vega for DESK_A broken down by deal'. Empty otherwise.",
    )


SYSTEM_PROMPT = """\
You are the orchestrator for a market-risk assistant. Each turn you decide,
one step at a time, how to handle the user's question — reasoning about what
the question actually NEEDS before invoking any machinery. Fetching MRX data
and running data analysis are tools you use ONLY when the question requires
them; many questions don't.

You are given:
- The user's question.
- The recent conversation (earlier questions and the answers already given).
- A summary of data already available (each dataset's description, columns,
  and a small sample) — data fetched this turn AND data fetched for earlier
  questions in this conversation (labelled "from an earlier question").

Choose exactly one action:

- "respond": answer the question DIRECTLY, in prose, with NO data fetch and NO
  code. Use this whenever the question does not require computing over a
  dataset — e.g. summarising or reflecting on the conversation so far,
  explaining a concept or acronym, answering a clarifying/meta question, or
  any general question. This is a valid answer even when NO data has been
  fetched. Prefer this when the question isn't fundamentally about crunching
  numbers from a dataset.

- "analyze": answer by COMPUTING over the available data (the system will
  generate and run pandas code, then narrate the result). Use this only when
  the question genuinely requires calculating, filtering, aggregating, or
  plotting a dataset that is already available — e.g. "what was the biggest
  daily variation", "plot the FX Vega evolution", "which desk dominates".
  Requires that relevant data is already available (fetched this turn or
  earlier in the conversation).

- "fetch": the data needed to answer isn't available yet — it needs a
  different date range, risk type, node, or breakdown that nothing already
  fetched contains. Put that ONE next fetch as a natural-language sub-question
  in fetch_query. You'll get another turn to decide after you see its result.
  Every fetch is a slow, costly call into a production risk system — only
  fetch when the question truly can't be answered from what's already here.

Always give a concrete `reasoning`: what the question needs, what data is or
isn't available, and why that leads to this action.
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


def _describe_history(history) -> str:
    """A compact summary of the recent conversation — prior questions and the
    narrated answers already given — so the orchestrator can decide "respond"
    questions that refer to the conversation itself (e.g. summaries, follow-ups
    referencing an earlier answer). `history` is a list of catalog.Turn (oldest
    first); empty on the first question.
    """
    if not history:
        return "(no earlier turns — this is the first question in the conversation)"
    chunks = []
    for turn in history:
        chunks.append(f"Q: {turn.question}\nA: {turn.narration}")
    return "\n\n".join(chunks)


def decide_next_step(llm, query: str, gathered, history=()) -> StepDecision:
    """Decide how to handle `query`: respond directly, analyze available data,
    or fetch new data. Given the `gathered` data so far (a list of (label, df)
    pairs) and the conversation `history` (a list of catalog.Turn, oldest
    first) so the orchestrator can answer conversation-level questions directly.

    Same structured-output mechanism as get_link — just a different schema and
    prompt. The loop (see loop.py) enforces the hard fetch cap and runs every
    fetch through the validation gate; this call only proposes the next action,
    it never executes one.
    """
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=(
            f"User's question: {query}\n\n"
            f"Recent conversation:\n{_describe_history(history)}\n\n"
            f"Data available:\n{_describe_gathered(gathered)}"
        )),
    ]
    structured_llm = llm.with_structured_output(StepDecision)
    return structured_llm.invoke(messages)
