"""The Executor loop — Claude-Code-shaped: one model, two tools, adaptive.

The blueprint is the checklist; the model interleaves fetch_mrx / run_python
until it can write the note (its final, tool-free message). All caps are plain
code: MAX_STEPS iterations, the fetch budget inside the fetch tool, parallel
fetch execution with the budget's lock. Amendments to the blueprint are the
model's prerogative (contract-of-qualities rule) — it states them in its
visible text, which lands in the trace.
"""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from ..common import knowledge
from ..common.events import EventKind
from ..common.trace import Step, timed
from .tools import fetch_mrx as fetch_tool
from .tools import run_python as python_tool

MAX_STEPS = 10

# Hard wall-clock cap per MRX fetch: a hung MRX/pymrx call (no timeout of its
# own) froze a live run for 5+ minutes. On timeout the loop proceeds — the
# model is told and can retry once or answer without that data. (The worker
# thread can't be killed in Python; it is abandoned and its late result
# discarded.)
FETCH_TIMEOUT_S = 180


class fetch_mrx(BaseModel):
    __doc__ = fetch_tool.TOOL_DESCRIPTION
    request: str = Field(description="the data needed, in natural language")


class run_python(BaseModel):
    __doc__ = python_tool.TOOL_DESCRIPTION
    code: str = Field(description="python code to execute in the persistent namespace")


class read_knowledge(BaseModel):
    """Read an MRX reference document — for questions ABOUT MRX itself (which
    views/risk types/parameters exist, what feeds a measure). Answer such
    questions from these documents; never guess codes or mechanics."""
    document: str = Field(description="one of: mrx_manual, risk_types_table, "
                                      "row_groupings_table, column_groupings_table, "
                                      "parameters_table")


LOOP_INSTRUCTIONS = """\
You are a market-risk analyst answering ONE question by fetching MRX data and
analyzing it in Python, then writing a desk note.

THE BLUEPRINT below is your checklist — the sections the answer must fill and
the fetches that feed them. It is a contract of QUALITIES, not a straitjacket:
if the data reality differs from the design, adapt — retitle/merge/split
sections — and SAY SO in your visible text with the reason. Never silently
drop what a section must establish; if its data is genuinely unavailable after
trying, say what is missing in one honest sentence.

Work adaptively: fetch what the blueprint needs now (you may request several
fetches at once — they run in parallel), look at the profiles, compute with
run_python, attach every table/chart to its section via section(), fetch the
targeted drills once you know what to target. Then — as your FINAL message
with NO tool calls — write the complete desk note in markdown: the executive
summary first (no heading), then one '## <section title>' per section in
blueprint order. The attached artifacts render under your text.
"""


def build_system_prompt(blueprint) -> str:
    return "\n\n".join([
        LOOP_INSTRUCTIONS,
        "=== THE BLUEPRINT ===\n" + blueprint.render_text(),
        knowledge.assemble(["mrx_reading", "mrx_semantics", "answer_standard", "desk_context"]),
    ])


# Extra iterations allowed for the single Critic-driven refine pass — the
# critique re-enters THE SAME loop with tools live, so "you never computed X"
# is fixed by computing X (the old pipeline's re-narration never could).
REFINE_STEPS = 4


def run_loop(loop_llm, url_llm, view, session, blueprint, question: str):
    """Iterate until the model answers (or the step cap forces the note).
    Returns (final_markdown, messages) — messages allow the refine re-entry."""
    bound = loop_llm.bind_tools([fetch_mrx, run_python, read_knowledge])
    opening = f"Question: {question}"
    if session.evidence:
        # Follow-up turns seed cached frames into the namespace — say so, or
        # the model guesses/refetches what it already has (a live audit
        # finding: the namespace was invisible at loop start).
        listing = "\n\n".join(f"[{e.label}] ({e.provenance})\n{e.profile.render_text()}"
                               for e in session.evidence)
        opening += ("\n\nALREADY IN YOUR NAMESPACE (fetched earlier in this "
                    "conversation — use directly, no fetch needed):\n" + listing)
    messages: List = [
        SystemMessage(content=build_system_prompt(blueprint)),
        HumanMessage(content=opening + "\n\nBegin."),
    ]
    note = _drive(bound, loop_llm, messages, session, url_llm, view, MAX_STEPS)
    return note, messages


def refine(loop_llm, url_llm, view, session, messages, critique_text: str) -> str:
    """ONE bounded refine: the critique re-enters the loop (tools live)."""
    bound = loop_llm.bind_tools([fetch_mrx, run_python, read_knowledge])
    messages.append(HumanMessage(content=(
        "A checker reviewed your note against the blueprint and the computed "
        f"artifacts and found issues:\n{critique_text}\n\nFix them — compute "
        "anything missing — then rewrite the COMPLETE note (same format).")))
    return _drive(bound, loop_llm, messages, session, url_llm, view, REFINE_STEPS)


def _drive(bound, loop_llm, messages, session, url_llm, view, max_steps: int) -> str:
    for step_num in range(1, max_steps + 1):
        response, elapsed = timed(lambda: bound.invoke(messages))
        messages.append(response)

        text = (response.content or "").strip() if isinstance(response.content, str) else ""
        if text:
            session.emit(EventKind.TOKEN, {"text": text})
        session.trace.append(Step(
            kind="agent", name="executor",
            summary=(text or f"{len(response.tool_calls)} tool call(s)")[:200],
            detail={"step": step_num,
                    "tool_calls": [{"name": tc["name"],
                                    "args": {k: str(v)[:200] for k, v in tc["args"].items()}}
                                   for tc in response.tool_calls]},
            elapsed_ms=elapsed,
        ))

        if not response.tool_calls:
            return text  # the note (or a clarifying/adapted answer)

        messages.extend(_execute_tool_calls(response.tool_calls, session, url_llm, view))

    # Step cap: force the note from what exists — never lose the work.
    session.trace.append(Step(kind="gate", name="step_cap", status="refused",
                              summary=f"step cap ({max_steps}) reached — forcing the note"))
    messages.append(HumanMessage(content=(
        "STEP LIMIT REACHED. Write the final desk note NOW from what is "
        "already computed — no more tool calls. Note honestly what could not "
        "be completed.")))
    final = loop_llm.invoke(messages)
    return (final.content or "").strip()


def _execute_tool_calls(tool_calls, session, url_llm, view) -> List[ToolMessage]:
    """Execute one response's tool calls: fetches in PARALLEL (the budget's
    lock keeps the cap exact), python sequentially in order. Results return in
    the original call order."""
    fetch_calls = [tc for tc in tool_calls if tc["name"] == "fetch_mrx"]
    results = {}

    if fetch_calls:
        # Always via the pool (even a single fetch) so the per-fetch wall
        # timeout applies. shutdown(wait=False): abandon hung workers instead
        # of blocking the loop on them.
        pool = ThreadPoolExecutor(max_workers=len(fetch_calls))
        futures = {tc["id"]: (tc, pool.submit(fetch_tool.fetch, session, url_llm, view,
                                              tc["args"].get("request", "")))
                   for tc in fetch_calls}
        for cid, (tc, future) in futures.items():
            try:
                results[cid] = future.result(timeout=FETCH_TIMEOUT_S)
            except FutureTimeout:
                request = tc["args"].get("request", "")
                session.trace.append(Step(kind="gate", name="fetch_timeout", status="failed",
                                          summary=f"fetch exceeded {FETCH_TIMEOUT_S}s: {request[:120]}"))
                session.emit(EventKind.ERROR,
                             {"message": f"fetch timed out after {FETCH_TIMEOUT_S}s: {request[:80]}"})
                results[cid] = (f"FETCH TIMED OUT after {FETCH_TIMEOUT_S}s — MRX did not "
                                f"respond for: {request!r}. Retry ONCE with a narrower "
                                f"request (shorter window / total instead of history), or "
                                f"proceed without this data and say so in the note.")
        pool.shutdown(wait=False)

    out = []
    for tc in tool_calls:
        if tc["name"] == "run_python":
            content = python_tool.run(session, tc["args"].get("code", ""))
        elif tc["name"] == "read_knowledge":
            content = knowledge.read_document(tc["args"].get("document", ""))
            session.trace.append(Step(kind="tool", name="read_knowledge",
                                      summary=f"read {tc['args'].get('document', '?')}"))
        elif tc["name"] == "fetch_mrx":
            content = results[tc["id"]]
            session.emit(EventKind.STATUS, {"label": "Fetched — analyzing…"})
        else:
            content = (f"unknown tool {tc['name']!r} — available: fetch_mrx, "
                       f"run_python, read_knowledge")
        out.append(ToolMessage(content=content, tool_call_id=tc["id"]))
    return out
