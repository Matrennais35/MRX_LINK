"""The Narrator — interprets; never computes.

Two modes, one per genuinely different job (ported from the proven prompts):
- synthesize(): the analyst-grade reading of computed Facts — BLUF headline,
  top drivers by materiality, concentration-vs-offsetting when that's the
  story, no level-by-level enumeration, no invented causal rationale.
- respond(): the direct prose answer for no-data questions (summaries,
  concept explanations), grounded in the conversation.

Plain text (streamed via the TOKEN event), not structured output — schema-
constraining the synthesis prose measurably flattens it; only the facts are
structured.
"""

from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from ..core.context import RunContext
from ..common.events import EventKind
from ..common.trace import Step, timed

SYNTHESIS_SYSTEM_PROMPT = """\
You are a senior market-risk analyst writing the daily
commentary for the desk head. You are given a market-risk question, the
analysis plan it was answered under, and the computed results (already correct
— do NOT recompute). Write a SHORT synthesis that reads like an experienced
analyst, not a readout of the table.

Rules — follow all of them:
- LEAD with ONE headline sentence that directly answers the question (bottom
  line up front): the net move and the single dominant driver belong here.
- Then the TOP 1-3 drivers only, ranked by materiality. For each: one sentence
  on what moved, one on what it likely means. Do NOT list every row.
- Call out CONCENTRATION vs. OFFSETTING explicitly when it's the real story —
  a big positive and a big negative that partly cancel, or one book dominating
  the net. This is usually the insight a human leads with.
- About 3-5 sentences total. No preamble.
- Do NOT enumerate aggregation levels ("by book...", "by book x deal...") as a
  structure — use the numbers to support ONE conclusion.
- Do NOT invent market/causal rationale the numbers don't support — but DO
  state every insight that is DERIVABLE from the numbers: a build of NEW
  positions vs. revaluation of existing ones, paired offsetting legs (a spread
  structure), concentration in one name. These are facts, not speculation —
  an answer that omits them is incomplete.
- Standard instrument/market-structure knowledge is ALLOWED when clearly
  labelled as context, never asserted as the cause (e.g. "context: USDHKD is a
  managed-band pair, so vega there is exposure to band stress").
- State the COB window/dates the data covers (from DATA CONTEXT) and give
  figures in the units as reported.
- The answer must satisfy the plan's success criteria.

Return ONLY the synthesis prose.
"""

RESPOND_SYSTEM_PROMPT = """\
You are a market-risk assistant answering a question DIRECTLY, in prose — no
data computation, no code. You are given the user's question, the recent
conversation, and short descriptions of any data fetched so far (descriptions
only, not the data itself).

Answer helpfully and concisely from that context. A request to summarise or
reflect on the conversation is answered from the conversation given; a general
or conceptual question is answered plainly. Do not invent specific numbers you
weren't given — refer to what was found in general terms rather than
fabricating figures. Respond with the answer only, no preamble.
"""


def _stream(llm, messages, ctx: RunContext) -> str:
    """Invoke (or stream, when the client supports it) and emit TOKEN events."""
    if hasattr(llm, "stream"):
        buffer = ""
        try:
            for chunk in llm.stream(messages):
                buffer += chunk.content
                ctx.emit(EventKind.TOKEN, {"text": buffer})
            return buffer
        except (NotImplementedError, AttributeError):
            pass
    text = llm.invoke(messages).content
    ctx.emit(EventKind.TOKEN, {"text": text})
    return text


def _data_context(ctx: RunContext) -> str:
    """What the fetches actually covered — COB window, risk-type mapping, the
    scout's assumptions. The narrator MUST have this: a real eval answer said
    'COB date not supplied' while the scout's own assumptions named it."""
    lines = []
    for e in ctx.evidence:
        if e.plan is None:
            continue
        lines.append(f"- {e.plan.intent}")
        for a in (e.plan.assumptions or [])[:4]:
            lines.append(f"    · {a}")
    return "\n".join(lines) or "(no fetch context)"


def _outline_block(ctx: RunContext) -> str:
    """The report structure the Narrator must write to — one '## <title>'
    heading per outlined section, each answering its own question from its own
    facts. Empty when no outline was planned (simple answers stay one blob)."""
    plan = ctx.plan
    outline = getattr(plan, "outline", None) or []
    if not outline:
        return ""
    lines = ["\n\nREPORT STRUCTURE — write the report EXACTLY as:",
             "1. Executive summary FIRST (no heading): 2-3 sentences, bottom line up front.",
             "2. Then ONE '## <title>' section per outline entry below, IN ORDER, each",
             "   answering ITS question from ITS OWN facts (marked [section: ...] in the",
             "   computed results). 1-3 sentences per section — the charts/tables render",
             "   under your text, so interpret them, don't re-list them. If a section's",
             "   facts are absent, say in ONE sentence what is missing — never invent."]
    for sec in outline:
        lines.append(f"- ## {sec.title} — answers: {sec.section_question}")
    return "\n".join(lines)


def synthesize(llm, ctx: RunContext, facts, *, refine_guidance: str = "") -> str:
    """The analyst report over computed Facts — structured to the plan's
    outline when one exists. `refine_guidance`, when set, is the Critic's
    named gaps for the single refine pass."""
    plan = ctx.plan
    guidance = f"\n\nREVISION GUIDANCE (fix exactly this):\n{refine_guidance}" if refine_guidance else ""
    messages = [
        SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Question: {ctx.query}\n"
            f"Target: {plan.target if plan else ctx.query}\n"
            f"Success criteria: {plan.success_criteria if plan else ''}\n\n"
            f"DATA CONTEXT (COB window, mappings — use for dates/units):\n{_data_context(ctx)}\n\n"
            f"COMPUTED RESULTS:\n{facts.render_text()}{_outline_block(ctx)}{guidance}"
        )),
    ]
    narrative, elapsed = timed(lambda: _stream(llm, messages, ctx).strip())
    ctx.trace.append(Step(kind="agent", name="narrator",
                          summary=narrative[:200], detail={"mode": "synthesize"},
                          elapsed_ms=elapsed))
    return narrative


def respond(llm, ctx: RunContext) -> str:
    """The direct prose answer for a needs_data=False question."""
    history = "\n\n".join(f"Q: {t.question}\nA: {t.narration}" for t in ctx.history) \
        or "(no earlier turns)"
    data = "\n".join(f"- {e.plan.intent if e.plan else e.label}" for e in ctx.evidence) \
        or "(no data fetched)"
    messages = [
        SystemMessage(content=RESPOND_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Question: {ctx.query}\n\n"
            f"Recent conversation:\n{history}\n\n"
            f"Data fetched so far:\n{data}"
        )),
    ]
    narrative, elapsed = timed(lambda: _stream(llm, messages, ctx).strip())
    ctx.trace.append(Step(kind="agent", name="narrator",
                          summary=narrative[:200], detail={"mode": "respond"},
                          elapsed_ms=elapsed))
    return narrative
