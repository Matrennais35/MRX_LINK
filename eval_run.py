"""Evaluation harness (v3 engine): run the question battery through
DESIGN -> EXECUTE -> WRITE and write ONE self-contained report with, per
question: the blueprint, the trace, the note with sections, embedded charts,
and QUANTITATIVE METRICS (per-phase timings, budget/reuse, python runs and
failures, timeouts, step counts, refine/clarification flags).

Edit CONVERSATIONS, run the whole file, send back eval_report_*.md.
Requires the live env (OIDC/APIGEE + pymrx).
"""

# ==============================================================================
CONVERSATIONS = [
    [  # A — the flagship deep-dive thread
        "Analyse the variation of FX Vega on GFXOPEMK over the last month.",
        "Which currency pair drove the increase since mid-month, and is the move concentrated or offsetting?",
        "Drill into the top pair: which tenors and deals explain its move?",
        "Summarise what we've found so far in this conversation.",
    ],
    [  # B — a different measure
        "Show IR Delta on IRUS by desk for the latest COB, compared with T-1.",
        "Plot the evolution of the total IR Delta on IRUS over the last two weeks.",
        "What is the biggest single-desk IR Delta change vs T-1, in absolute terms?",
    ],
    ["What is the total EQ Delta Cash for US_SPX in GLEQD as of the latest COB?"],
    ["What does FX Vega measure, and why might it jump at month-end?"],
    ["Analyse GFXOPEMK."],
    # — the 4 response-mode stress questions —
    ["What MRX files are used for FX Gamma?"],
    ["Extract the portfolio list under GFXOPEMK."],
    ["What is the main underlying of the FX Targets products in GFXOPEMK?"],
    ["Plot the EQ PV Diff for all spot shifts as of yesterday."],
]

MAX_FETCHES = None
# ==============================================================================

import base64
import io
import traceback
from datetime import datetime
from pathlib import Path

from mrx_analyst import run as runner
from mrx_analyst.common import llm as llm_factory
from mrx_analyst.common.errors import PipelineError
from mrx_analyst.storage import catalog


def _metrics(result) -> dict:
    trace = result.session.trace
    return {
        "sections": len(result.answer.sections),
        "unfilled": sum(1 for s in result.answer.sections if s.status == "unfilled"),
        "budget": f"{result.session.budget.used}/{result.session.budget.max_fetches}",
        "reused": sum(1 for s in trace if s.name == "reuse"),
        "py_runs": len(result.session.code_log),
        "py_failed": sum(1 for s in trace if s.name == "run_python" and s.status == "failed"),
        "timeouts": sum(1 for s in trace if s.name == "fetch_timeout"),
        "loop_steps": sum(1 for s in trace if s.name == "executor"),
        "refined": "yes" if any(s.name == "critic" and s.detail.get("verdict") == "revise"
                                for s in trace) else "no",
        "clarified": "yes" if getattr(result.blueprint, "clarification", "") else "no",
        "design_s": f"{result.timings.get('design', 0):.0f}",
        "execute_s": f"{result.timings.get('execute', 0):.0f}",
        "critique_s": f"{result.timings.get('critique', 0):.0f}",
        "total_s": f"{sum(result.timings.values()):.0f}",
    }


def _summary_table(rows) -> str:
    cols = ["q", "conv", "question", "status", "sections", "unfilled", "budget",
            "reused", "py_runs", "py_failed", "timeouts", "loop_steps",
            "refined", "clarified", "design_s", "execute_s", "critique_s", "total_s"]
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = ["| " + " | ".join(str(r.get(c, "-")) for c in cols) + " |" for r in rows]
    return "\n".join([head, sep] + body)


def report_turn(n, question, result, error=None) -> str:
    out = [f"\n\n{'=' * 78}\n## Q{n}: {question}\n{'=' * 78}"]
    if error is not None:
        out.append(f"\n### RUN FAILED\n```\n{error}\n```")
        return "\n".join(out)

    out.append("\n### THE BLUEPRINT\n```\n" + result.blueprint.render_text() + "\n```")

    out.append(f"\n### TRACE ({len(result.session.trace)} steps)")
    for i, s in enumerate(result.session.trace, 1):
        flag = "" if s.status == "ok" else f" [{s.status.upper()}]"
        out.append(f"{i}. [{s.kind}] {s.name}{flag} ({s.elapsed_ms}ms) — {s.summary[:160]}")

    out.append("\n### THE NOTE")
    out.append(f"\n> {result.answer.narrative}")
    for section in result.answer.sections:
        flag = "" if section.status == "filled" else f"  **[UNFILLED: {section.reason}]**"
        out.append(f"\n**§ {section.title}**{flag}")
        if section.text:
            out.append(f"> {section.text}")
        if section.table is not None:
            cap = None if section.full_table else 25
            out.append("```\n" + section.table.head(cap).to_string() + "\n```")

    for k, fig in enumerate(result.answer.charts, 1):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        out.append(f"\n![chart Q{n}.{k}](data:image/png;base64,{b64})")

    out.append("\n### CODE RUN (audit)")
    for code in result.session.code_log:
        out.append("```python\n" + code + "\n```")
    return "\n".join(out)


llm = {e: llm_factory.get_llm(model="gpt55", version="2024-06-01", reasoning_effort=e)
       for e in ("high", "medium", "low")}
llm["tools"] = llm_factory.get_llm(model="gpt55", version="2024-06-01", reasoning_effort=None)
if not llm or all(v is None for v in llm.values()):
    raise SystemExit("get_llm returned None — check OIDC/APIGEE env vars.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
report_path = Path(f"eval_report_{stamp}.md")
sections, rows = [], []
n = 0
for g, questions in enumerate(CONVERSATIONS, 1):
    conversation_id = catalog.new_conversation_id()
    print(f"\n=== conversation {g} ({len(questions)} question(s)) ===")
    for question in questions:
        n += 1
        print(f"\n>>> Q{n}: {question}")
        kwargs = dict(session_id="eval", conversation_id=conversation_id)
        if MAX_FETCHES is not None:
            kwargs["max_fetches"] = MAX_FETCHES
        result, error = None, None
        try:
            result = runner.run_question(llm, question, **kwargs)
            m = _metrics(result)
            print(f"    ok — {m['total_s']}s · budget {m['budget']} · "
                  f"{m['sections']} sections ({m['unfilled']} unfilled) · "
                  f"refined={m['refined']} clarified={m['clarified']}")
            rows.append({"q": n, "conv": g, "question": question[:50], "status": "ok", **m})
        except PipelineError as e:
            error = f"{type(e).__name__}: {e}" + (f"\nURL: {e.url}" if getattr(e, "url", None) else "")
            print(f"    FAILED: {error}")
            rows.append({"q": n, "conv": g, "question": question[:50], "status": "FAILED"})
        except Exception:
            error = traceback.format_exc()
            print(f"    CRASHED:\n{error}")
            rows.append({"q": n, "conv": g, "question": question[:50], "status": "CRASHED"})
        sections.append(report_turn(n, question, result, error))

header = [
    "# MRX Analyst v3 — evaluation report",
    f"run: {stamp} · {n} questions across {len(CONVERSATIONS)} conversations",
    "", "## Metrics (scan this first)", _summary_table(rows),
]
report_path.write_text("\n".join(header) + "".join(sections), encoding="utf-8")
print(f"\nreport written: {report_path}")
