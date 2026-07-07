"""Debug harness for the mrx_analyst rebuild (notebook-style): run ONE question
through the agent pipeline and print EVERYTHING — the plan, every agent
decision and tool run, fetch gates/budget, the computed facts, and the answer.

How to use: edit QUESTION (and CONVERSATION_ID for a follow-up) below, then run
the whole file — in Jupyter, paste into a cell; or `python analyst_debug.py`.
Requires the same live env as the app (OIDC/APIGEE env vars + real pymrx).
"""

# ==============================================================================
# EDIT THESE, THEN RUN THE WHOLE FILE
# ==============================================================================
QUESTION = "analyse the variation of FX Vega on GFXOPEMK over the last month"

# Paste a previous run's conversation id here to ask a follow-up over its data.
CONVERSATION_ID = None

# Optionally tighten the hard fetch budget while experimenting (None = 6).
MAX_FETCHES = None
# ==============================================================================


import sys
import textwrap

from mrx_analyst.common import llm as llm_factory
from mrx_analyst.core import orchestrator
from mrx_analyst.common.errors import PipelineError
from mrx_analyst.storage import catalog


class C:
    _on = sys.stdout.isatty()
    HEAD = "\033[1;36m" if _on else ""
    STEP = "\033[1;33m" if _on else ""
    KEY = "\033[0;35m" if _on else ""
    DIM = "\033[2m" if _on else ""
    OK = "\033[0;32m" if _on else ""
    ERR = "\033[0;31m" if _on else ""
    OFF = "\033[0m" if _on else ""


def rule(title=""):
    line = "=" * 78
    print(f"\n{C.HEAD}{line}\n{title}\n{line}{C.OFF}" if title else f"{C.DIM}{line}{C.OFF}")


def emit(kind, payload):
    """Live event printer — the single channel, routed by kind."""
    if kind == "status":
        print(f"  {C.DIM}· {payload['label']}{C.OFF}")
    elif kind == "agent":
        print(f"  {C.STEP}» {payload['role']}{C.OFF} decided")
    elif kind == "tool":
        print(f"  {C.DIM}· tool: {payload['name']}{C.OFF}")
    elif kind == "fetch":
        url = payload.get("url", "")
        print(f"  {C.DIM}· fetch {payload['stage']}: {payload.get('label','')}"
              + (f"\n    {url}" if url and payload["stage"] == "fetching" else "") + C.OFF)
    elif kind == "error":
        print(f"  {C.ERR}! {payload['message']}{C.OFF}")
        if payload.get("url"):
            print(f"    {C.KEY}MRX URL that failed:{C.OFF} {payload['url']}")


conversation_id = CONVERSATION_ID or catalog.new_conversation_id()

rule("QUESTION")
print(f"  {QUESTION}")
print(f"  conversation_id: {conversation_id}")
print(f"  {C.DIM}(set CONVERSATION_ID = {conversation_id!r} for a follow-up){C.OFF}")

rule("LIVE EVENTS")
llm = {e: llm_factory.get_llm(model="gpt55", version="2024-06-01", reasoning_effort=e)
        for e in ("high", "medium", "low")}

if not llm or all(v is None for v in llm.values()):
    print(f"{C.ERR}get_llm returned None — check OIDC/APIGEE env vars.{C.OFF}")
else:
    kwargs = dict(session_id="debug", conversation_id=conversation_id, emit=emit)
    if MAX_FETCHES is not None:
        kwargs["max_fetches"] = MAX_FETCHES
    try:
        result = orchestrator.run_turn(llm, QUESTION, **kwargs)
    except PipelineError as e:
        rule("FAILED")
        print(f"{C.ERR}{type(e).__name__}: {e}{C.OFF}")
        if getattr(e, "url", None):
            print(f"\n  {C.KEY}MRX URL that failed (open it to diagnose):{C.OFF}\n  {e.url}")
    else:
        ctx = result.ctx

        rule("THE PLAN (how the Planner approached it)")
        plan = ctx.plan
        if plan:
            print(f"  {C.KEY}target:{C.OFF} {plan.target}")
            print(f"  {C.KEY}approach:{C.OFF} {plan.approach}")
            print(f"  {C.KEY}representation:{C.OFF} {plan.representation}")
            print(f"  {C.KEY}success criteria:{C.OFF} {plan.success_criteria}")
            print(f"  {C.KEY}needs_data:{C.OFF} {plan.needs_data}  "
                  f"{C.KEY}goals:{C.OFF} {plan.fetch_goals}")

        rule(f"TRACE ({len(ctx.trace)} steps — every decision, tool run, and gate)")
        for i, step in enumerate(ctx.trace, start=1):
            flag = "" if step.status == "ok" else f"  [{step.status.upper()}]"
            print(f"\n{C.STEP}{i}. [{step.kind}] {step.name}{flag}{C.OFF} "
                  f"{C.DIM}({step.elapsed_ms}ms){C.OFF}")
            print(textwrap.indent(step.summary, "   "))

        rule("EVIDENCE (datasets + profiles the agents reasoned over)")
        for e in ctx.evidence:
            print(f"\n  {C.KEY}[{e.label}] ({e.provenance}){C.OFF}")
            print(textwrap.indent(e.profile.render_text(), "    "))
            if e.plan is not None:
                print(f"    {C.DIM}MRX URL: {e.plan.url}{C.OFF}")

        rule("ANSWER")
        print(result.answer.narrative)
        if result.answer.value is not None:
            print(f"\n  {C.KEY}value:{C.OFF} {result.answer.value}")
        if result.answer.table is not None:
            print(f"\n{C.KEY}table:{C.OFF}")
            print(textwrap.indent(result.answer.table.to_string(), "  "))
        if result.answer.chart is not None:
            print(f"\n  {C.KEY}chart:{C.OFF} (figure produced — shown in the app)")
        print(f"\n  {C.DIM}budget used: {ctx.budget.used}/{ctx.budget.max_fetches}{C.OFF}")
        rule()
        print(f"{C.OK}done — follow up by setting CONVERSATION_ID = {conversation_id!r}{C.OFF}")
