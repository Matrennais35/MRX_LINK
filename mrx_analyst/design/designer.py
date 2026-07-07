"""The Answer Designer — the pivotal step (VISION.md's central insight).

ONE reasoning act holding the question (intent), the MRX capability MENU, and
the gold-standard PRINCIPLES — producing the Blueprint: what the output should
look like given what MRX can serve, and the data plan that fills it. Every
prompt piece comes from knowledge/ files; improving the Designer means editing
markdown.
"""

from typing import List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from ..common import knowledge
from .blueprint import Blueprint

DESIGNER_INSTRUCTIONS = """\
You are the ANSWER DESIGNER for a market-risk assistant. Given the user's
question, design what the ANSWER should look like — before any data is
touched — as a blueprint: the note's sections (each a quality contract: what
it must establish, from which data, shown how) and the minimal set of MRX
fetches that fill them.

Method:
1. Derive the TARGET (see: reading the question).
2. Pick the RESPONSE MODE and derive THIS question's bar from the answer
   standard — only the sections the question earns; a lookup gets one
   section, an extraction is the table itself, never pad.
3. Design fetches from the CAPABILITY MENU: single-dimension cuts; history
   form for any path question; explain-type risk types for "why did it
   change"; targeted (filtered) drills marked "after: <section>" when their
   parameters depend on what an earlier section reveals.
4. Data already available (profiles below, reusable at zero cost) counts —
   design the same request for it rather than a new cut when it covers a need.
5. ASSUME-THEN-RUN: when the question is under-specified but reasonably
   interpretable, DO NOT ask back — make explicit reasonable assumptions
   (window, COB, measure, scope), record them in `assumptions`, and design
   the full answer; the note states them so the user can refine. Set
   `clarification` ONLY when the ambiguity would materially change the
   answer and no sensible default exists.
"""


def build_system_prompt() -> str:
    return "\n\n".join([
        DESIGNER_INSTRUCTIONS,
        knowledge.assemble(["intent", "answer_standard", "mrx_menu", "desk_context"]),
    ])


def design(llm, question: str, *, history: Optional[List] = None,
           available_data: str = "", redesign_context: str = "") -> Blueprint:
    """Produce the Blueprint. `available_data` is the profiles of this
    conversation's cached datasets; `redesign_context`, when set, is the
    Executor's data-reality report for the ONE bounded redesign."""
    history_block = "\n\n".join(
        f"Q: {t.question}\nA: {t.narration}" for t in (history or [])
    ) or "(first question in the conversation)"
    content = (
        f"Question: {question}\n\n"
        f"Recent conversation:\n{history_block}\n\n"
        f"Data already available (reusable at zero cost):\n{available_data or '(none)'}"
    )
    if redesign_context:
        content += (
            "\n\nREDESIGN — the data reality differs from the original design; "
            f"redesign the FETCH STRATEGY (keep the target):\n{redesign_context}"
        )
    messages = [SystemMessage(content=build_system_prompt()),
                HumanMessage(content=content)]
    return llm.with_structured_output(Blueprint).invoke(messages)
