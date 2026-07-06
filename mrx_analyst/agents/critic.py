"""The Critic — the ANCHORED quality gate on the final answer.

Checks the narrative against two verifiable anchors: the plan's own
success_criteria (the bar the Planner set up front) and the computed Facts
table (every number in the narrative must appear in / follow from it). This is
deliberately NOT an open-ended "improve this" pass — un-anchored self-critique
measurably degrades answers; anchored checking is what works.

The orchestrator enforces the cap: on "revise", exactly ONE refine pass
(numeric issues re-enter the Analyst, narrative issues re-enter the Narrator),
then the answer ships regardless. The cap lives in plain code, not in this
prompt.
"""

from typing import List

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from ..core.agent import Agent
from ..core.context import RunContext


class Issue(BaseModel):
    kind: str = Field(description='"numeric" (a number is wrong/unsupported by the table), '
                                  '"missing" (a required computation/data is absent from the results — '
                                  'rewording cannot fix it), or "narrative" (criteria unmet, '
                                  'structure/claim problems fixable by rewriting)')
    detail: str = Field(description="the specific defect, concretely — what to fix")


class Critique(BaseModel):
    verdict: str = Field(description='"pass" or "revise"')
    issues: List[Issue] = Field(default_factory=list,
                                description="empty on pass; the concrete defects on revise")


CRITIC_SYSTEM_PROMPT = """\
You are the quality gate on a market-risk answer. You are given the success
criteria the analysis plan set, the computed results table (ground truth), and
the narrative that will be shown to the user. Check EXACTLY two things:

1. NUMBERS: every figure the narrative states must appear in, or directly
   follow from, the computed results. A number that isn't supported is a
   "numeric" issue (quote the number and what the table actually shows).
2. CRITERIA: the narrative must satisfy each success criterion. An unmet
   criterion whose REQUIRED ANALYSIS IS ABSENT FROM THE COMPUTED RESULTS is a
   "missing" issue (rewriting prose cannot fix it — name the missing
   computation). An unmet criterion the results DO support, an unanswered
   target, or an invented causal story is a "narrative" issue.

Do NOT judge style, tone, or length. Do NOT suggest improvements beyond the
two checks. If both checks pass, verdict is "pass" with no issues — passing a
good answer is the common case, not a failure of diligence.
"""


class Critic(Agent):
    role = "critic"
    system_prompt = CRITIC_SYSTEM_PROMPT
    Output = Critique

    def __init__(self, facts=None, narrative: str = ""):
        self._facts = facts
        self._narrative = narrative

    def build_messages(self, ctx: RunContext) -> list:
        plan = ctx.plan
        return [HumanMessage(content=(
            f"Question: {ctx.query}\n"
            f"Success criteria: {plan.success_criteria if plan else '(none set)'}\n\n"
            f"COMPUTED RESULTS (ground truth):\n"
            f"{self._facts.render_text() if self._facts else '(no computation — direct answer)'}\n\n"
            f"NARRATIVE TO CHECK:\n{self._narrative}"
        ))]
