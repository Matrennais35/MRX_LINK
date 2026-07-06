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


# ---------------------------------------------------------------------------
# STAGE 0.5 — the analysis plan: reason about the question BEFORE fetching.
# ---------------------------------------------------------------------------

class AnalysisPlan(BaseModel):
    """The orchestrator's reasoned plan for a question, produced before any
    fetch. Not a retrieved template and not a rigid script — a fresh reasoning
    artifact that sets DIRECTION (target, breakdown, representation) and the bar
    for a good answer (success_criteria). The investigate loop still adapts to
    what each fetch actually returns; this just makes every step purposeful
    instead of reactive. See docs/reasoning_orchestrator_design.md.
    """

    target: str = Field(
        description="The question BEHIND the question — what the user is really "
        "trying to learn. Not a restatement of their words; the decision or "
        "insight they need. E.g. for 'what drove the FX Vega increase' the "
        "target is 'which book/deal/pair drove the net increase, and whether "
        "it's a concentrated position or an offsetting round-trip'."
    )
    approach: str = Field(
        description="The reasoned analysis approach: which breakdown(s) to look "
        "at, in what order, and WHY each one reveals the target. Reason like an "
        "analyst — start broad (the net move), then decompose along the "
        "dimension most likely to explain it, then drill into the dominant part. "
        "State the reasoning, not just the steps."
    )
    representation: str = Field(
        description="How the answer should be SHOWN to best serve the target — "
        "chosen by reasoning about the question type, not a default. E.g. a "
        "contribution waterfall for attribution ('what drove X'), a ranked "
        "table + bar for 'top contributors', an evolution line for a trend over "
        "time, a single number for a lookup. Say which and why."
    )
    success_criteria: str = Field(
        description="What a GOOD answer to this MUST contain to actually serve "
        "the target — the bar the final answer is held to. E.g. 'states the net "
        "move, names the single dominant driver, and flags whether the move is "
        "concentrated or offsetting'. Specific and checkable."
    )


PLAN_SYSTEM_PROMPT = """\
You are a senior market-risk analyst planning HOW to answer a question before
touching any data. Think the way an experienced analyst thinks about a problem
— reason about it, don't pattern-match it to a template.

For the question, work out four things:

1. TARGET — the question behind the question. What decision or insight does the
   user actually need? A request to "analyse the variation" isn't answered by a
   number; it's answered by explaining what moved and why it matters. Name the
   real target, not a restatement.

2. APPROACH — how to get there. Reason about which breakdown would actually
   reveal the target. The analyst's instinct: establish the net move first, then
   decompose along the dimension most likely to explain it (by book, by
   currency pair, by deal, by tenor — whichever fits THIS question), then drill
   into whatever dominates. Say which breakdowns, in what order, and WHY each
   one earns its place. Don't over-fetch: only the cuts that move you toward the
   target.

3. REPRESENTATION — how the answer should be shown to best serve the target.
   Reason about the question type: attribution ("what drove X") is a story of
   contributions that add to a net — a waterfall or a signed ranked bar shows
   that far better than a plain table. A ranking wants a bar. A trend over time
   wants a line. A single fact wants a number, no chart. Pick the representation
   the target deserves and say why.

4. SUCCESS_CRITERIA — what a good answer MUST contain to genuinely serve the
   target. This is the bar the final answer will be held to, so make it specific
   and checkable (e.g. "states the net move; names the dominant driver; flags
   concentration vs. offsetting"), not generic ("is accurate and clear").

This is a PLAN, not a script — the data you fetch may change the picture and
that's expected. You're setting direction and the quality bar, not locking in
every step.
"""


def plan_analysis(llm, query: str, gathered=(), history=()) -> AnalysisPlan:
    """Reason about a question BEFORE fetching: what's the real target, what
    breakdown reveals it, how should it be shown, and what makes a good answer.
    One structured-output call (same mechanism as get_link/decide_next_step).

    `gathered`/`history` give the planner what this conversation already knows,
    so a follow-up plans against existing data rather than from scratch.
    """
    messages = [
        SystemMessage(content=PLAN_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Question: {query}\n\n"
            f"Already available in this conversation:\n{_describe_gathered(gathered)}\n\n"
            f"Recent conversation:\n{_describe_history(history)}"
        )),
    ]
    return llm.with_structured_output(AnalysisPlan).invoke(messages)


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
    target_progress: str = Field(
        default="",
        description="What the data gathered so far DOES and does NOT yet show "
        "toward the analysis target — the gap. E.g. 'the by-book cut shows the "
        "net move and names the top book, but not which deals within it drove "
        "it — still missing the deal-level drill'. This gap is what justifies "
        "the action below.",
    )
    reasoning: str = Field(
        description="Why this action follows from the gap above — what the question needs and "
        "what the available data does or doesn't show. Recorded for audit and shown to the user."
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
- THE ANALYSIS PLAN — the target (what the user really needs), the approach
  (which breakdowns reveal it, in what order), and success criteria. Your job
  each step is to move the gathered data toward that target. Fetch the cuts the
  approach calls for; stop fetching once the data can satisfy the success
  criteria.
- The recent conversation (earlier questions and the answers already given).
- A summary of data already available (each dataset's description, columns,
  and a small sample) — data fetched this turn AND data fetched for earlier
  questions in this conversation (labelled "from an earlier question").

First state `target_progress`: what the available data DOES and does NOT yet
show toward the target — the gap. Then choose the action that best closes that
gap. When the data already covers the success criteria, don't keep fetching —
move to "analyze".

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


def _describe_plan(plan) -> str:
    """The analysis plan, rendered for the step-decision and answer prompts.
    Empty string when no plan was produced (a trivial lookup path), so those
    prompts read exactly as before this stage existed."""
    if plan is None:
        return ""
    return (
        f"Target: {plan.target}\n"
        f"Approach: {plan.approach}\n"
        f"Representation the answer should use: {plan.representation}\n"
        f"A good answer must: {plan.success_criteria}"
    )


def decide_next_step(llm, query: str, gathered, history=(), plan=None) -> StepDecision:
    """Decide how to handle `query`: respond directly, analyze available data,
    or fetch new data. Given the `gathered` data so far (a list of (label, df)
    pairs), the conversation `history`, and the `plan` (an AnalysisPlan, or None
    for a trivial path) so each step is argued against the target rather than
    guessed.

    Same structured-output mechanism as get_link — just a different schema and
    prompt. The loop (see loop.py) enforces the hard fetch cap and runs every
    fetch through the validation gate; this call only proposes the next action,
    it never executes one.
    """
    plan_block = _describe_plan(plan)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=(
            f"User's question: {query}\n\n"
            + (f"Analysis plan:\n{plan_block}\n\n" if plan_block else "")
            + f"Recent conversation:\n{_describe_history(history)}\n\n"
            f"Data available:\n{_describe_gathered(gathered)}"
        )),
    ]
    structured_llm = llm.with_structured_output(StepDecision)
    return structured_llm.invoke(messages)
