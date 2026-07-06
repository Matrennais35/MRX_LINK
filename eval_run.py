"""Evaluation harness: run question(s) through the full agent pipeline and
write ONE complete report file — every stage's full output (Planner target/
approach, every DataScout spec + MRX URL, every fetch + full data profile, the
Analyst's ops, the facts table, the narrative, the Critic's verdict, timings,
budget) — designed to be sent back for evaluation of what's working and what
isn't, stage by stage.

How to use: edit CONVERSATIONS below (each inner list runs as ONE conversation,
so later questions in a group evaluate follow-up/reuse/drill behavior), run the
whole file (Jupyter cell or `python eval_run.py`), then send back the generated
eval_report_*.md — ONE self-contained file, charts embedded inline.
Requires the live env (OIDC/APIGEE + pymrx), same as the app.
"""

# ==============================================================================
# EDIT THESE, THEN RUN THE WHOLE FILE
# ==============================================================================
# Each inner list is ONE conversation (later questions in a group test
# follow-up/reuse/drill behavior); each group starts a fresh conversation.
# The battery below probes each capability separately — adjust nodes/measures
# to ones you know exist, but keep the STRUCTURE (deep-dive thread / second
# measure thread / one-shots) so the insights stay separable.
CONVERSATIONS = [
    [  # A — the flagship deep-dive thread: attribution -> reuse -> drill -> respond
        "Analyse the variation of FX Vega on GFXOPEMK over the last month.",
        "Which currency pair drove the increase since mid-month, and is the move concentrated or offsetting?",
        "Drill into the top pair: which tenors and deals explain its move?",
        "Summarise what we've found so far in this conversation.",
    ],
    [  # B — a different measure: T-1 compare (variance op), trend, reuse-lookup
        "Show IR Delta on IRUS by desk for the latest COB, compared with T-1.",
        "Plot the evolution of the total IR Delta on IRUS over the last two weeks.",
        "What is the biggest single-desk IR Delta change vs T-1, in absolute terms?",
    ],
    [  # C1 — a plain lookup (number answer, minimal machinery, COB T-1 handling)
        "What is the total EQ Delta Cash for US_SPX in GLEQD as of the latest COB?",
    ],
    [  # C2 — a concept question (respond path, no data; also probes whether it
       #      invents market rationale it can't support)
        "What does FX Vega measure, and why might it jump at month-end?",
    ],
    [  # C3 — deliberately underspecified (insight into how the Planner handles
       #      ambiguity — today it guesses; this shows us WHAT it guesses)
        "Analyse GFXOPEMK.",
    ],
]

MAX_FETCHES = None   # None = default budget (6) per question
# ==============================================================================

import base64
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


def report_turn(number: int, question: str, result, error=None, chart_b64=None) -> str:
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
    if chart_b64:
        # The chart embedded directly — the report is one self-contained file.
        out.append(f"\n![chart Q{number}](data:image/png;base64,{chart_b64})")
    elif result.answer.chart is not None:
        out.append("(a chart was produced but could not be embedded)")
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


def _summary_row(n, group, question, result, error) -> dict:
    row = {"q": n, "conv": group, "question": question[:60],
           "status": "ok", "budget": "-", "evidence": "-",
           "codegen": "-", "critic": "-", "ms": "-"}
    if error is not None:
        row["status"] = "FAILED"
        return row
    ctx = result.ctx
    row["budget"] = f"{ctx.budget.used}/{ctx.budget.max_fetches}"
    row["evidence"] = len(ctx.evidence)
    row["codegen"] = "yes" if any(s.name == "codegen" for s in ctx.trace) else "no"
    critics = [s for s in ctx.trace if s.kind == "agent" and s.name == "critic"]
    row["critic"] = critics[-1].detail.get("verdict", "-") if critics else "(none)"
    row["ms"] = sum(s.elapsed_ms for s in ctx.trace)
    return row


def _summary_table(rows) -> str:
    head = "| # | conv | question | status | budget | evidence | codegen | critic | traced ms |"
    sep = "|---|------|----------|--------|--------|----------|---------|--------|-----------|"
    body = [f"| {r['q']} | {r['conv']} | {r['question']} | {r['status']} | {r['budget']} "
            f"| {r['evidence']} | {r['codegen']} | {r['critic']} | {r['ms']} |" for r in rows]
    return "\n".join([head, sep] + body)


def run_and_report(llm, conversations, *, max_fetches=None, out_dir=".") -> str:
    """Run the question groups (one conversation each); write ONE aggregated
    report: a cross-question summary table first, then every question's full
    per-stage section. Returns the report path."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(out_dir) / f"eval_report_{stamp}.md"

    sections, rows = [], []
    n = 0
    for g, questions in enumerate(conversations, start=1):
        conversation_id = catalog.new_conversation_id()
        print(f"\n=== conversation {g} ({len(questions)} question(s)) ===")
        for question in questions:
            n += 1
            print(f"\n>>> Q{n}: {question}")
            kwargs = dict(session_id="eval", conversation_id=conversation_id)
            if max_fetches is not None:
                kwargs["max_fetches"] = max_fetches
            result, error, chart_b64 = None, None, None
            try:
                result = orchestrator.run_turn(llm, question, **kwargs)
                print(f"    ok — budget {result.ctx.budget.used}, "
                      f"{len(result.ctx.evidence)} evidence, "
                      f"{len(result.ctx.trace)} trace steps")
                if result.answer.chart is not None:
                    buf = io.BytesIO()
                    result.answer.chart.savefig(buf, format="png", bbox_inches="tight", dpi=110)
                    chart_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                    print("    chart embedded in the report")
            except PipelineError as e:
                error = f"{type(e).__name__}: {e}" + (f"\nURL: {e.url}" if getattr(e, "url", None) else "")
                print(f"    FAILED: {error}")
            except Exception:
                error = traceback.format_exc()
                print(f"    CRASHED:\n{error}")
            rows.append(_summary_row(n, g, question, result, error))
            sections.append(report_turn(n, question, result, error, chart_b64=chart_b64))

    header = [
        "# MRX Analyst — evaluation report",
        f"run: {stamp} · {n} questions across {len(conversations)} conversations · "
        f"budget: {max_fetches or 'default(6)'} per question",
        "",
        "## Summary (scan this first)",
        _summary_table(rows),
    ]
    report_path.write_text("\n".join(header) + "".join(sections), encoding="utf-8")
    print(f"\nreport written: {report_path}")
    return str(report_path)


if __name__ == "__main__":  # true for `python eval_run.py` AND a pasted Jupyter cell
    _llm = {e: llm_factory.get_llm(model="gpt55", version="2024-06-01", reasoning_effort=e)
        for e in ("high", "medium", "low")}
    if not _llm or all(v is None for v in _llm.values()):
        print("get_llm returned None — check OIDC/APIGEE env vars (same as the app).")
    else:
        run_and_report(_llm, CONVERSATIONS, max_fetches=MAX_FETCHES)
