"""Debug harness (notebook-style): run ONE question through the controller loop
and print EVERYTHING — the orchestrator's decision + reasoning at each step, the
MRX plan/URL, reuse-vs-fetch, dataframe shapes, generated pandas code, and the
final answer. For validating "does the orchestrator make good decisions" against
a real LLM + real MRX, which fake-LLM tests can't tell you.

How to use: edit QUESTION (and CONVERSATION_ID for a follow-up) just below,
then run the whole file — in Jupyter, paste it into a cell and run; or
`python debug_run.py`. Requires the same live env as `streamlit run app.py`
(OIDC/APIGEE env vars + real pymrx).
"""

# ==============================================================================
# EDIT THESE, THEN RUN THE WHOLE FILE
# ==============================================================================
QUESTION = "analyse the variation of FX Vega on GFXOPEMK over the last month"

# To ask a FOLLOW-UP that reuses earlier data, paste the conversation id printed
# by a previous run here (e.g. "conv_abc123"). Leave as None to start fresh.
CONVERSATION_ID = None

# Optionally tighten the hard fetch cap while experimenting (None = default).
MAX_FETCHES = None
# ==============================================================================


import sys
import textwrap

from mrx.pipeline import catalog, connect_llm, loop
from mrx.pipeline.pipeline_errors import PipelineError


# ---- pretty-printing helpers -------------------------------------------------

class C:
    """ANSI colors — makes the trace scannable. Auto-off when not a tty."""
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
    if title:
        print(f"\n{C.HEAD}{line}\n{title}\n{line}{C.OFF}")
    else:
        print(f"{C.DIM}{line}{C.OFF}")


def kv(key, value, indent=2):
    print(f"{' ' * indent}{C.KEY}{key}:{C.OFF} {value}")


def block(label, text, indent=2):
    pad = " " * indent
    print(f"{pad}{C.KEY}{label}:{C.OFF}")
    for line in str(text).splitlines() or [""]:
        print(f"{pad}  {line}")


def dump_plan(view):
    """The MRX plan behind a fetched view — intent, reasoning, assumptions, and
    the actual MRX URL (the 'mrx link')."""
    plan = view.plan
    print(f"      {C.KEY}--- MRX plan ---{C.OFF}")
    kv("intent", plan.intent, indent=6)
    kv("view_reasoning", plan.view_reasoning, indent=6)
    kv("parameters", plan.parameters, indent=6)
    if plan.assumptions:
        kv("assumptions", "; ".join(plan.assumptions), indent=6)
    kv("confidence", plan.confidence, indent=6)
    if plan.needs_clarification:
        kv("needs_clarification", plan.needs_clarification, indent=6)
    kv("SmartDF question", plan.SmartDF, indent=6)
    kv("MRX URL", plan.url, indent=6)


def dump_result(result):
    rule("INVESTIGATION TRACE (the orchestrator's step-by-step reasoning)")
    for step in result.steps:
        print(f"\n{C.STEP}Step {step.step_num} — {step.action.upper()}{C.OFF}"
              f"{'  (CAPPED)' if step.capped else ''}")
        block("reasoning", step.reasoning)
        if step.action == "fetch" and not step.capped:
            kv("fetch_query", step.fetch_query)
            kv("resolved to", step.fetched_label)
            kv("source", "REUSED cached data" if step.reused_dataset_id else "FETCHED from MRX")

    rule("DATA GATHERED (with the MRX plan / URL behind each view)")
    if not result.views:
        print(f"  {C.DIM}(none — answered directly, no data fetched){C.OFF}")
    for i, view in enumerate(result.views, start=1):
        tag = "reused (from earlier)" if view.reused_dataset_id else "fetched this turn"
        print(f"\n  {C.KEY}[{i}] {view.plan.intent}{C.OFF}  ({tag})")
        kv("query", view.query, indent=6)
        kv("dataframe shape", view.df.shape, indent=6)
        kv("columns", list(view.df.columns), indent=6)
        print(f"      {C.DIM}first rows:{C.OFF}")
        print(textwrap.indent(view.df.head(5).to_string(), "        "))
        dump_plan(view)

    rule("FINAL ANSWER")
    ans = result.answer
    kv("type", ans.type)
    block("narration", ans.narration)
    if ans.method:
        block("method", ans.method)
    if ans.code:
        block("generated code", ans.code)
    if ans.type == "chart":
        kv("value", "(matplotlib figure — run app.py to view it)")
    else:
        kv("value", repr(ans.value)[:500])


# ---- run it ------------------------------------------------------------------

conversation_id = CONVERSATION_ID or catalog.new_conversation_id()

rule("QUESTION")
print(f"  {QUESTION}")
kv("conversation_id", conversation_id)
print(f"  {C.DIM}(set CONVERSATION_ID = {conversation_id!r} to ask a follow-up){C.OFF}")

rule("LIVE STAGES (fire during the run)")


def on_stage(stage):
    print(f"  {C.DIM}· stage: {stage}{C.OFF}")


_streamed = {"n": 0}
def on_token(buffer):
    if len(buffer) - _streamed["n"] > 40:  # throttle
        _streamed["n"] = len(buffer)
        print(f"  {C.DIM}· streaming answer... ({len(buffer)} chars){C.OFF}")


llm = connect_llm.get_llm(model="gpt55", version="2024-06-01")

if llm is None:
    # Notebook-friendly: print, don't sys.exit (which raises in a Jupyter cell).
    print(f"{C.ERR}get_llm returned None — check OIDC/APIGEE env vars (same as app.py).{C.OFF}")
else:
    _kwargs = dict(on_stage=on_stage, on_token=on_token, conversation_id=conversation_id)
    if MAX_FETCHES is not None:
        _kwargs["max_fetches"] = MAX_FETCHES

    try:
        result = loop.run_agent_loop(llm, QUESTION, **_kwargs)
    except PipelineError as e:
        rule("FAILED")
        print(f"{C.ERR}{type(e).__name__}: {e}{C.OFF}")
        failed_url = getattr(e, "url", None)
        if failed_url:
            print(f"\n  {C.KEY}MRX URL that failed (open it to see MRX's own error):{C.OFF}")
            print(f"  {failed_url}")
    else:
        dump_result(result)
        rule()
        print(f"{C.OK}done — for a follow-up, set CONVERSATION_ID = {conversation_id!r} and rerun{C.OFF}")
