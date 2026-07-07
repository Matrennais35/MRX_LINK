"""P2 VERTICAL SLICE — run ONE question through DESIGN -> EXECUTE -> WRITE live
and print everything: the blueprint, the loop's trace, the note, and the
PER-PHASE TIMINGS (the latency baseline the plan gates on).

Edit QUESTION below, run the whole file (Jupyter cell or `python slice_run.py`).
Requires the live env (OIDC/APIGEE + pymrx), same as the app.
"""

# ==============================================================================
QUESTION = "Analyse the variation of FX Vega on GFXOPEMK over the last month."
CONVERSATION_ID = None      # paste a previous run's id for a follow-up
MAX_FETCHES = None          # None = default budget (6)
# ==============================================================================

import sys
import textwrap

from mrx_analyst import run as runner
from mrx_analyst.common import llm as llm_factory
from mrx_analyst.common.errors import PipelineError
from mrx_analyst.storage import catalog


def rule(title=""):
    line = "=" * 78
    print(f"\n{line}\n{title}\n{line}" if title else line)


def emit(kind, payload):
    if kind == "status":
        print(f"  · {payload['label']}")
    elif kind == "agent":
        print(f"  » designer produced the blueprint")
    elif kind == "fetch":
        stage, label = payload.get("stage"), payload.get("label", "")
        print(f"  · fetch {stage}: {label}")
        if payload.get("url") and stage == "fetching":
            print(f"    {payload['url']}")
    elif kind == "token":
        text = (payload.get("text") or "").strip()
        if text:
            print(textwrap.indent(text[:600], "  | "))
    elif kind == "error":
        print(f"  ! {payload.get('message', '')}")


conversation_id = CONVERSATION_ID or catalog.new_conversation_id()
rule("QUESTION")
print(f"  {QUESTION}\n  conversation_id: {conversation_id}")

llm = {e: llm_factory.get_llm(model="gpt55", version="2024-06-01", reasoning_effort=e)
       for e in ("high", "medium", "low")}
# the tool-calling loop client omits reasoning_effort (Azure 400 otherwise)
llm["tools"] = llm_factory.get_llm(model="gpt55", version="2024-06-01", reasoning_effort=None)

if not llm or all(v is None for v in llm.values()):
    print("get_llm returned None — check OIDC/APIGEE env vars.")
    sys.exit(1)

rule("LIVE")
kwargs = dict(session_id="slice", conversation_id=conversation_id, emit=emit)
if MAX_FETCHES is not None:
    kwargs["max_fetches"] = MAX_FETCHES

try:
    result = runner.run_question(llm, QUESTION, **kwargs)
except PipelineError as e:
    rule("FAILED")
    print(f"{type(e).__name__}: {e}")
    if getattr(e, "url", None):
        print(f"MRX URL that failed:\n{e.url}")
    sys.exit(1)

rule("THE BLUEPRINT (the pivotal step)")
print(result.blueprint.render_text())

rule(f"TRACE ({len(result.session.trace)} steps)")
for i, step in enumerate(result.session.trace, 1):
    flag = "" if step.status == "ok" else f" [{step.status.upper()}]"
    print(f"{i}. [{step.kind}] {step.name}{flag} ({step.elapsed_ms}ms) — {step.summary[:150]}")

rule("THE NOTE")
print(result.answer.narrative)
for section in result.answer.sections:
    print(f"\n## {section.title}" + ("" if section.status == "filled" else f"  [UNFILLED: {section.reason}]"))
    if section.text:
        print(section.text)
    if section.table is not None:
        print(textwrap.indent(section.table.head(15).to_string(), "  "))
    if section.chart is not None:
        print("  (chart produced)")

rule("TIMINGS (the latency baseline)")
for phase, seconds in result.timings.items():
    print(f"  {phase:10s} {seconds:7.1f}s")
print(f"  {'TOTAL':10s} {sum(result.timings.values()):7.1f}s"
      f"   · budget used: {result.session.budget.used}/{result.session.budget.max_fetches}"
      f"   · python runs: {len(result.session.code_log)}")
rule()
print(f"follow-up: set CONVERSATION_ID = {conversation_id!r}")
