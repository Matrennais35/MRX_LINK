"""The DataScout — designs the MRX views that serve the plan's fetch goals.

Produces a MultiFetchPlan of FetchSpecs, each embedding a complete MRXPlan
(the URL + reasoning contract the validation gate checks). Its system prompt
is the authoritative MRX knowledge: the multirow manual + reference tables
(the SAME files the validation gate parses — belt and braces: the scout picks
codes from the real tables, and validation still hard-rejects anything not in
them), plus multi-view planning instructions.

Two-wave adaptivity: wave-1 specs are what can be designed BEFORE seeing data
(overview + independent breakdowns). When the scout sets `drill_after_overview`
it is re-invoked once AFTER wave 1 with the fetched profiles, so a drill can
target what the overview actually shows ("book X dominates -> drill X") instead
of guessing. The orchestrator owns both waves; the scout only proposes.
"""

from typing import List, Optional

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from ..core.agent import Agent
from ..core.context import RunContext
from ..core.models import MRXPlan
from ..views.multirow import generate_link


class FetchSpec(BaseModel):
    role: str = Field(description='"overview" | "breakdown" | "drill" — what this view is for')
    justification: str = Field(description="which fetch goal this serves and why this cut serves it")
    mrx_plan: MRXPlan


class MultiFetchPlan(BaseModel):
    specs: List[FetchSpec] = Field(
        description="The complementary views to fetch NOW (wave 1) — only what "
        "can be designed before seeing any data. Keep it minimal: every fetch "
        "is a costly call into a production risk system."
    )
    drill_after_overview: bool = Field(
        default=False,
        description="True when the approach needs a drill whose parameters depend "
        "on what the overview shows (e.g. 'drill into whichever book dominates') — "
        "you'll be asked again with the fetched data's profiles.",
    )
    reasoning: str = Field(description="the view-design reasoning, for the audit trace")


_MULTI_FETCH_INSTRUCTIONS = """

--- MULTI-VIEW FETCH PLANNING ---

You design the SET of MRX views that serve the analysis plan's fetch goals —
each spec embeds a complete, valid MRX plan built exactly per the manual and
tables above (never invent codes; dates follow the COB T-1 rules in §8).

- Design ONLY what can be decided before seeing any data: typically one
  overview (the net/evolution picture) and the independent breakdown(s) the
  approach calls for. One spec per goal is the norm; never more than 3 specs.
- If the approach requires drilling into whatever the overview REVEALS (the
  dominant book/pair/desk), do NOT guess the drill now — set
  drill_after_overview=true and you will be re-invoked with the fetched data's
  profiles to design the drill precisely.
- If data already available (listed below, reusable at zero cost) covers a
  goal, design the SAME view for it anyway (matching params) — the system
  reuses it without a fetch; a different view when the existing data genuinely
  doesn't cover the goal.
- When re-invoked after a failed fetch, fix the specific problem named and
  keep everything else the same.
"""


def _scout_system_prompt() -> str:
    # manual.md + the four reference tables (cached load, same files the
    # validation gate parses) + the multi-view planning contract.
    return generate_link.build_system_prompt() + _MULTI_FETCH_INSTRUCTIONS


class DataScout(Agent):
    role = "datascout"
    Output = MultiFetchPlan

    def __init__(self):
        self.system_prompt = _scout_system_prompt()

    def build_messages(self, ctx: RunContext) -> list:
        plan = ctx.plan
        goals = "\n".join(f"- {g}" for g in (plan.fetch_goals if plan else [])) or "- answer the question"
        available = "\n".join(
            f"- {e.label}: {e.plan.intent if e.plan else e.label} "
            f"(params: {e.plan.url if e.plan else 'n/a'})"
            for e in ctx.evidence
        ) or "(none)"
        profiles = "\n\n".join(
            f"[{e.label}] ({e.provenance})\n{e.profile.render_text()}"
            for e in ctx.evidence if e.provenance in ("fetched", "reused")
        )
        content = (
            f"Question: {ctx.query}\n\n"
            f"Analysis plan target: {plan.target if plan else ctx.query}\n"
            f"Approach: {plan.approach if plan else ''}\n\n"
            f"Fetch goals:\n{goals}\n\n"
            f"Data already available (reusable at zero cost):\n{available}"
        )
        if profiles:
            content += (
                "\n\nPROFILES OF DATA FETCHED SO FAR (design the drill from what "
                f"these actually show):\n{profiles}"
            )
        errors = getattr(ctx, "_scout_errors", "")
        if errors:
            content += (
                "\n\nPREVIOUS FETCHES FAILED — design corrected view(s) for ONLY "
                f"the failed goals, fixing the specific problems named:\n{errors}"
            )
        return [HumanMessage(content=content)]
