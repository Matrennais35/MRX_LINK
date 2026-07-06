"""The Planner — reasons about the question BEFORE any data is touched.

Produces the AnalysisPlan every later stage is held to: the real target, the
approach (which breakdowns reveal it, in what order, and why), the
representation the answer deserves, and checkable success criteria (the
Critic's rubric). Also decides `needs_data` — a summary/concept/meta question
short-circuits straight to the Narrator with no fetch machinery at all.

Prompt seeded from the proven PLAN_SYSTEM_PROMPT (reason like an analyst, no
templates), extended with needs_data/fetch_goals and a compact statement of
what MRX can break down by (families, not the full 360-code table — the
DataScout holds the authoritative tables).
"""

from typing import List

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from ..core.agent import Agent
from ..core.context import RunContext


class SectionSpec(BaseModel):
    """One planned report section — the structure-first contract everything
    downstream fills: fetches serve its needs, ops are tagged to it, the
    Narrator writes its text, the Critic checks it against its own question."""
    title: str = Field(description="short section heading, e.g. 'The path', 'Drivers'")
    section_question: str = Field(
        description="the specific question THIS section answers — the quality "
        "bar it is checked against (e.g. 'when did the move happen: steady "
        "drift or dated jumps?')"
    )
    needs: str = Field(
        description="what evidence/computation fills it (drives the fetch "
        "goals), e.g. 'daily total series over the window; largest daily moves'"
    )
    artifact: str = Field(
        description='how it is shown: "line chart" | "waterfall" | "ranked bar" '
        '| "table" | "ranked bar + table" | "none" (prose-only)'
    )


class AnalysisPlan(BaseModel):
    target: str = Field(
        description="The question BEHIND the question — what the user is really "
        "trying to learn; the decision or insight they need, not a restatement."
    )
    approach: str = Field(
        description="The reasoned analysis approach: which breakdown(s) to look at, "
        "in what order, and WHY each one reveals the target. Start broad (the net "
        "move), decompose along the dimension most likely to explain it, then drill "
        "into what dominates."
    )
    representation: str = Field(
        description="How the answer should be SHOWN to serve the target — e.g. a "
        "contribution waterfall for attribution, a ranked table + bar for top "
        "contributors, an evolution line for a trend, a single number for a lookup."
    )
    success_criteria: str = Field(
        description="What a GOOD answer MUST contain — specific and checkable "
        "(e.g. 'states the net move; names the dominant driver; flags concentration "
        "vs. offsetting'), never generic. The final answer is judged against this."
    )
    needs_data: bool = Field(
        description="False when the question can be answered directly in prose with "
        "NO data fetch or computation (a conversation summary, a concept/acronym "
        "explanation, a meta question). True when it needs MRX data."
    )
    fetch_goals: List[str] = Field(
        default_factory=list,
        description="When needs_data: the 1-3 data GOALS the approach requires, each "
        "one sentence, DERIVED FROM the outline sections' needs (e.g. 'daily FX Vega "
        "series for the node over June', 'the change decomposed by book'). Goals, "
        "not URLs — the DataScout designs the actual views.",
    )
    outline: List[SectionSpec] = Field(
        default_factory=list,
        description="When needs_data: the REPORT OUTLINE — 2-5 ordered sections the "
        "answer will be structured as. Design it for THIS question; a simple lookup "
        "gets ONE section, a full variation analysis gets the sections its story "
        "needs. Empty when needs_data is false.",
    )


PLANNER_SYSTEM_PROMPT = """\
You are a senior market-risk analyst planning HOW to answer a question before
touching any data. Reason about THIS question — don't pattern-match it to a
template.

Work out:

1. TARGET — the question behind the question. What decision or insight does the
   user actually need? "Analyse the variation" isn't answered by a number; it's
   answered by explaining what moved and why it matters.

2. APPROACH — how to get there. The analyst instinct: establish the net move
   first, then decompose along the dimension most likely to explain it, then
   drill into whatever dominates. MRX can break a figure down by (families):
   book, deal/security, currency, currency pair/underlying, tenor, desk,
   portfolio, product, risk type, node, strike, maturity, issuer, guarantor.
   Say which breakdowns, in what order, and WHY each earns its place — and
   don't over-fetch: only the cuts that move you toward the target.

3. REPRESENTATION — how the answer should be shown. Attribution ("what drove
   X") is contributions adding to a net — a waterfall or signed ranked bar. A
   ranking wants a bar. A trend wants a line. A single fact wants a number and
   no chart.

4. SUCCESS_CRITERIA — the checkable bar for a good answer (the final answer is
   judged against this, so be specific: "states the net move; names the
   dominant driver; flags concentration vs. offsetting").

5. NEEDS_DATA — false for questions answerable directly in prose (conversation
   summaries, concept explanations, meta questions): the system then answers
   without touching MRX at all. True otherwise, with 1-3 fetch_goals (data
   GOALS in plain language — a separate specialist designs the actual views).

6. OUTLINE — when data is needed, design the ANSWER'S REPORT STRUCTURE up
   front: 2-5 ordered sections, each with the question it answers, the
   evidence/computation that fills it, and how it is shown. Reason the outline
   from the target — as method (never a template): a change/variation story
   usually needs the PATH (dated moves, not just endpoint difference), the
   DRIVERS (signed attribution), and — when deal-level data can be fetched —
   WHAT'S UNDERNEATH (new positions vs. closed vs. revaluation of existing
   ones); a plain lookup needs ONE section; a ranking needs the ranking and
   maybe its concentration. Every fetch goal must serve a section's needs,
   and success_criteria should demand what the outline promises.

This is a PLAN, not a script — fetched data may change the picture, and the
drill step adapts to what the overview shows. You set direction and the bar.
"""


class Planner(Agent):
    role = "planner"
    system_prompt = PLANNER_SYSTEM_PROMPT
    Output = AnalysisPlan

    def build_messages(self, ctx: RunContext) -> list:
        history = "\n\n".join(
            f"Q: {t.question}\nA: {t.narration}" for t in ctx.history
        ) or "(first question in the conversation)"
        available = "\n".join(
            f"- {e.label}: {e.plan.intent if e.plan else e.label}" for e in ctx.evidence
        ) or "(no data fetched yet in this conversation)"
        return [HumanMessage(content=(
            f"Question: {ctx.query}\n\n"
            f"Recent conversation:\n{history}\n\n"
            f"Data already available (reusable at zero cost):\n{available}"
        ))]
