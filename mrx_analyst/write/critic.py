"""The Critic — ONE anchored check of the note against the blueprint and the
computed artifacts. Deliberately narrow (open-ended self-critique degrades
answers; anchored checking works):

1. NUMBERS: every figure in the note must appear in, or directly derive from,
   the computed artifacts.
2. CONTRACTS: each blueprint section's must_establish is delivered — or
   honestly flagged with a data-based reason (amendments with stated reasons
   are legitimate; silent drops are findings).

Findings re-enter the EXECUTOR (which can compute what's missing) — one
bounded refine, cap in code, then the note ships regardless.
"""

from typing import List

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field


class Issue(BaseModel):
    kind: str = Field(description='"numeric" (a figure is unsupported by the artifacts), '
                                  '"missing" (a section contract was silently dropped / its '
                                  'computation never ran), or "narrative" (a claim the data '
                                  'does not support)')
    detail: str = Field(description="the specific defect — quote the number/claim and what "
                                    "the artifacts actually show")
    section: str = Field(default="", description="the section title concerned, when applicable")


class Critique(BaseModel):
    verdict: str = Field(description='"pass" or "revise"')
    issues: List[Issue] = Field(default_factory=list,
                                description="empty on pass; concrete defects on revise")

    def render_text(self) -> str:
        return "\n".join(f"- [{i.kind}] ({i.section}) {i.detail}" if i.section
                         else f"- [{i.kind}] {i.detail}" for i in self.issues)


CRITIC_SYSTEM_PROMPT = """\
You are the quality gate on a market-risk note. You are given the question,
the BLUEPRINT (each section's contract), the COMPUTED ARTIFACTS (ground
truth), and the NOTE. Check EXACTLY two things:

1. NUMBERS: every figure the note states must appear in, or directly follow
   from, the artifacts ("numeric" issue: quote the figure and what the
   artifacts show).
2. CONTRACTS: each blueprint section's must_establish is delivered, or
   honestly flagged with a data-based reason. An amendment WITH a stated
   reason is legitimate. A contract silently dropped, or whose computation
   never ran, is a "missing" issue. An invented causal story is "narrative".

Do NOT judge style, tone, or length. Passing a good note is the common case,
not a failure of diligence.
"""


def check(llm, question: str, blueprint, note: str, artifacts_text: str) -> Critique:
    messages = [
        SystemMessage(content=CRITIC_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Question: {question}\n\n"
            f"BLUEPRINT (the contracts):\n{blueprint.render_text()}\n\n"
            f"COMPUTED ARTIFACTS (ground truth):\n{artifacts_text or '(none)'}\n\n"
            f"NOTE TO CHECK:\n{note}"
        )),
    ]
    return llm.with_structured_output(Critique).invoke(messages)
