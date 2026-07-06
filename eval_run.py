"""Evaluation harness: run question(s) through the full agent pipeline and
write ONE complete report file — every stage's full output (Planner target/
approach, every DataScout spec + MRX URL, every fetch + full data profile, the
Analyst's ops, the facts table, the narrative, the Critic's verdict, timings,
budget) — designed to be sent back for evaluation of what's working and what
isn't, stage by stage.

How to use: edit QUESTIONS below (several questions run in ONE conversation,
so follow-up/reuse behavior is evaluated too), run the whole file (Jupyter cell
or `python eval_run.py`), then send back the generated eval_report_*.md.
Requires the live env (OIDC/APIGEE + pymrx), same as the app.
"""

# ==============================================================================
# EDIT THESE, THEN RUN THE WHOLE FILE
# ==============================================================================
QUESTIONS = [
    "Analyse the variation of FX Vega on GFXOPEMK over the last month.",
    "Which currency pair drove the increase since mid-month, and is it concentrated?",
]

MAX_FETCHES = None   # None = default budget (6)
# ==============================================================================

import io
import traceback
from datetime import datetime
from pathlib import Path

from mrx_analyst.core import llm as llm_factory
from mrx_analyst.core import orchestrator
from mrx_analyst.core.errors import PipelineError
from mrx_analyst.storage import catalog


# ---- report building ---------------------------------------------------------

def _fmt_detail(detail: dict, indent: str = "  ") -> str:
    lines = []
    for key, value in detail.items():
        text = str(value)
        if "\n" in text or len(text) > 100:
            lines.append(f"{indent}{key}:")
            for ln in text.splitlines():
                lines.append(f"{indent}  {ln}")
        else:
            lines.append(f"{indent}{key}: {text}")
    return "\n".join(lines)


def _agent_steps(ctx, name):
    return [s for s in ctx.trace if s.kind == "agent" and s.name == name]


def report_turn(number: int, question: str, result, error=None) -> str:
    """One question's full evaluation section."""
    out = [f"\n\n{'=' * 78}\n## Q{number}: {question}\n{'=' * 78}"]

    if error is not None:
        out.append(f"\n### RUN FAILED\n```\n{error}\n```")
        if result is None:
            return "\n".join(out)

    ctx = result.ctx

    # -- timings -----------------------------------------------------------
    out.append("\n### Timings")
    total_ms = sum(s.elapsed_ms for s in ctx.trace)
    for s in ctx.trace:
        if s.elapsed_ms:
            out.append(f"- {s.kind}:{s.name} — {s.elapsed_ms} ms")
    out.append(f"- **total traced: {total_ms} ms** · budget used: "
               f"{ctx.budget.used}/{ctx.budget.max_fetches}")

    # -- 1. planner ----------------------------------------------------------
    out.append("\n### 1. PLANNER")
    for step in _agent_steps(ctx, "planner"):
        out.append(_fmt_detail(step.detail))

    # -- 2. datascout (all calls: wave 1, wave 2, re-plans) -------------------
    out.append("\n### 2. DATASCOUT (each call, in order)")
    for i, step in enumerate(_agent_steps(ctx, "datascout"), start=1):
        out.append(f"\n**call {i}:** reasoning: {step.detail.get('reasoning', '')}")
        out.append(f"drill_after_overview: {step.detail.get('drill_after_overview')}")
        for j, spec in enumerate(step.detail.get("specs", []), start=1):
            plan = spec.get("mrx_plan", {})
            out.append(f"\n- spec {j} [{spec.get('role')}] — {spec.get('justification', '')}")
            out.append(f"  intent: {plan.get('intent')}")
            out.append(f"  assumptions: {plan.get('assumptions')} · confidence: {plan.get('confidence')}")
            out.append(f"  URL: `{plan.get('url')}`")

    # -- 3. fetches + evidence -------------------------------------------------
    out.append("\n### 3. FETCHES & EVIDENCE (with full data profiles)")
    for s in ctx.trace:
        if s.kind == "gate":
            flag = "" if s.status == "ok" else f" [{s.status.upper()}]"
            out.append(f"- gate:{s.name}{flag} — {s.summary}")
            if s.detail.get("url"):
                out.append(f"  URL: `{s.detail['url']}`")
    for e in ctx.evidence:
        out.append(f"\n**[{e.label}]** ({e.provenance})"
                   + (f" — {e.plan.intent}" if e.plan is not None else ""))
        if e.plan is not None:
            out.append(f"URL: `{e.plan.url}`")
        out.append("```\n" + e.profile.render_text() + "\n```")

    # -- 4. analyst --------------------------------------------------------------
    out.append("\n### 4. ANALYST (each proposal, in order)")
    for i, step in enumerate(_agent_steps(ctx, "analyst"), start=1):
        out.append(f"\n**proposal {i}:** {step.detail.get('reasoning', '')}")
        for op in step.detail.get("ops", []):
            out.append(f"- op: {op.get('tool')}  args: `{op.get('args_json')}`")
        if step.detail.get("fallback_code_request"):
            out.append(f"- fallback requested: {step.detail['fallback_code_request']}")
    for s in ctx.trace:
        if s.kind == "tool":
            flag = "" if s.status == "ok" else f" [{s.status.upper()}]"
            out.append(f"- executed:{s.name}{flag} — {s.summary}")
            if s.name == "codegen" and s.detail.get("code"):
                out.append("```python\n" + s.detail["code"] + "\n```")

    # -- 5. facts table -----------------------------------------------------------
    out.append("\n### 5. FACTS TABLE")
    if result.answer.table is not None:
        out.append("```\n" + result.answer.table.head(50).to_string() + "\n```")
    else:
        out.append("(no table)")
    if result.answer.chart is not None:
        out.append("(a chart was produced — PNG saved alongside this report)")
    if result.answer.value is not None:
        out.append(f"value: {result.answer.value}")

    # -- 6. narrative(s) ------------------------------------------------------------
    narrator_steps = _agent_steps(ctx, "narrator")
    out.append("\n### 6. NARRATIVE" + (" (refined — both versions below)" if len(narrator_steps) > 1 else ""))
    out.append(f"\n> {result.answer.narrative}")

    # -- 7. critic --------------------------------------------------------------------
    out.append("\n### 7. CRITIC")
    for step in _agent_steps(ctx, "critic"):
        out.append(f"verdict: {step.detail.get('verdict')}")
        for issue in step.detail.get("issues", []):
            out.append(f"- [{issue.get('kind')}] {issue.get('detail')}")
    if len(narrator_steps) > 1:
        out.append(f"(refine pass ran: first draft was — {narrator_steps[0].summary})")

    # -- 8. raw trace ---------------------------------------------------------------------
    out.append("\n### 8. RAW TRACE")
    for i, s in enumerate(ctx.trace, start=1):
        flag = "" if s.status == "ok" else f" [{s.status.upper()}]"
        out.append(f"{i}. [{s.kind}] {s.name}{flag} ({s.elapsed_ms}ms) — {s.summary}")

    return "\n".join(out)


def run_and_report(llm, questions, *, max_fetches=None, out_dir=".") -> str:
    """Run the questions in one conversation; write and return the report path."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(out_dir) / f"eval_report_{stamp}.md"
    conversation_id = catalog.new_conversation_id()

    header = [
        "# MRX Analyst — evaluation report",
        f"run: {stamp} · conversation: {conversation_id} · "
        f"budget: {max_fetches or 'default(6)'}",
        f"questions: {len(questions)} (run sequentially in ONE conversation — "
        "later questions evaluate follow-up/reuse behavior)",
    ]
    sections = []

    for n, question in enumerate(questions, start=1):
        print(f"\n>>> Q{n}: {question}")
        kwargs = dict(session_id="eval", conversation_id=conversation_id)
        if max_fetches is not None:
            kwargs["max_fetches"] = max_fetches
        result, error = None, None
        try:
            result = orchestrator.run_turn(llm, question, **kwargs)
            print(f"    ok — budget {result.ctx.budget.used}, "
                  f"{len(result.ctx.evidence)} evidence, "
                  f"{len(result.ctx.trace)} trace steps")
            if result.answer.chart is not None:
                png = Path(out_dir) / f"eval_chart_{stamp}_q{n}.png"
                buf = io.BytesIO()
                result.answer.chart.savefig(buf, format="png", bbox_inches="tight", dpi=110)
                png.write_bytes(buf.getvalue())
                print(f"    chart saved: {png.name}")
        except PipelineError as e:
            error = f"{type(e).__name__}: {e}" + (f"\nURL: {e.url}" if getattr(e, "url", None) else "")
            print(f"    FAILED: {error}")
        except Exception:
            error = traceback.format_exc()
            print(f"    CRASHED:\n{error}")
        sections.append(report_turn(n, question, result, error))

    report_path.write_text("\n".join(header) + "".join(sections), encoding="utf-8")
    print(f"\nreport written: {report_path}")
    return str(report_path)


if __name__ == "__main__":  # true for `python eval_run.py` AND a pasted Jupyter cell
    _llm = llm_factory.get_llm(model="gpt55", version="2024-06-01")
    if _llm is None:
        print("get_llm returned None — check OIDC/APIGEE env vars (same as the app).")
    else:
        run_and_report(_llm, QUESTIONS, max_fetches=MAX_FETCHES)
