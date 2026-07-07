"""P3 REVIEW HARNESS — run the DESIGNER ALONE over the review questions and
write every blueprint into one markdown for the user's red pen.

This is the cheap way to judge the pivotal step at breadth: 14 blueprints on
paper (the 10 eval-battery questions + the 4 mode-stressing questions), no
fetches, no analysis — just "did the Designer derive the right bar and the
right response mode for each?"

Edit QUESTIONS if needed, run the whole file. Requires the live env.
"""

# Each inner list is ONE conversation: follow-ups see synthetic history of the
# earlier questions (design-only harness — no data exists, so history carries
# the QUESTIONS asked; the designer must still design, not clarify, when the
# referent is in the thread).
CONVERSATIONS = [
    ["Analyse the variation of FX Vega on GFXOPEMK over the last month.",
     "Which currency pair drove the increase since mid-month, and is the move concentrated or offsetting?",
     "Drill into the top pair: which tenors and deals explain its move?",
     "Summarise what we've found so far in this conversation."],
    ["Show IR Delta on IRUS by desk for the latest COB, compared with T-1.",
     "Plot the evolution of the total IR Delta on IRUS over the last two weeks.",
     "What is the biggest single-desk IR Delta change vs T-1, in absolute terms?"],
    ["What is the total EQ Delta Cash for US_SPX in GLEQD as of the latest COB?"],
    ["What does FX Vega measure, and why might it jump at month-end?"],
    ["Analyse GFXOPEMK."],
    # — the 4 response-mode stress questions (user-supplied) —
    ["What MRX files are used for FX Gamma?"],
    ["Extract the portfolio list under GFXOPEMK."],
    ["What is the main underlying of the FX Targets products in GFXOPEMK?"],
    ["Plot the EQ PV Diff for all spot shifts as of yesterday."],
]

import time
from datetime import datetime
from pathlib import Path

from mrx_analyst.common import llm as llm_factory
from mrx_analyst.design import designer

llm = llm_factory.get_llm(model="gpt55", version="2024-06-01", reasoning_effort="high")
if llm is None:
    raise SystemExit("get_llm returned None — check OIDC/APIGEE env vars.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out_path = Path(f"blueprints_{stamp}.md")
lines = [f"# Designer review — {sum(len(g) for g in CONVERSATIONS)} blueprints ({stamp})",
         "", "Judge each: right response mode? right sections/bar? right fetches "
         "(shape + window pinned)? clarification only when truly warranted?", ""]

class _Turn:
    def __init__(self, question):
        self.question = question
        self.narration = "(answered earlier in this conversation)"


n = 0
flat = [(g, q) for g, group in enumerate(CONVERSATIONS, 1) for q in group]
history_by_group = {}
for g, question in flat:
    n += 1
    print(f">>> Q{n} (conv {g}): {question}")
    history = history_by_group.setdefault(g, [])
    t0 = time.monotonic()
    try:
        blueprint = designer.design(llm, question, history=list(history))
        seconds = time.monotonic() - t0
        lines += [f"\n---\n\n## Q{n} · conv {g} ({seconds:.0f}s): {question}", "",
                  "```", blueprint.render_text(), "```"]
        history.append(_Turn(question))
        print(f"    ok in {seconds:.0f}s — {len(blueprint.sections)} sections, "
              f"{len(blueprint.fetches)} fetches"
              + (" · CLARIFICATION" if blueprint.clarification else ""))
    except Exception as e:  # a failed design is itself review material
        lines += [f"\n---\n\n## Q{n} · conv {g} (FAILED): {question}", "", f"```\n{e}\n```"]
        print(f"    FAILED: {e}")

out_path.write_text("\n".join(lines), encoding="utf-8")
print(f"\nwritten: {out_path} — send it back for the red-pen review")
