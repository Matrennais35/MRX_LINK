"""run_python — free pandas/matplotlib in the session's persistent namespace.

TOTAL freedom (any code); `helpers` is an optional library on the bench, and
`section(title, table=, chart=)` is the delivery convention attaching computed
artifacts to blueprint sections. Errors return as text so the loop model
self-corrects in the next iteration. Same trust model as the proven sandbox
(internal users, internal data); output capped for the context window.
"""

import contextlib
import io
import traceback

from ...common.trace import Step, timed

MAX_OUTPUT_CHARS = 8000  # room for section() echoes + the model's prints

TOOL_DESCRIPTION = (
    "Run Python over the fetched dataframes (they are in the namespace under "
    "their registered labels). The namespace PERSISTS across calls. print() "
    "what you need to see; the output comes back to you.\n"
    "Available: pd, np, plt, section(), and `helpers` — tested, Depth-"
    "hierarchy-safe ops (exact signatures):\n"
    "- helpers.ops.trend(df, top_jumps=3) -> {'table': jumps table with "
    "Date/Value/Change, 'tables': {'trend_series': long df}, 'start', 'end', "
    "'net', 'pct_change', 'largest_jump_date'} — for wide History frames.\n"
    "- helpers.ops.variance(df, group_cols, current_col, previous_col, "
    "top_n=10) -> DataFrame[group..., current, previous, delta, pct_change] "
    "sorted by |delta| — for compare frames.\n"
    "- helpers.ops.attribution(df, group_cols, value_col, top_n=10) -> "
    "DataFrame[group..., contribution, share_of_net].\n"
    "- helpers.ops.concentration(df, group_col, value_col) -> "
    "{'table', 'top1_share', 'top5_share', 'hhi'} (group_col is ONE string).\n"
    "- helpers.ops.position_change(df, label_cols, current_col, previous_col, "
    "top_n=5, as_of='YYYY-MM-DD') -> {'table', 'tables', new/expired/"
    "unwound/existing buckets} (label_cols is a LIST).\n"
    "- helpers.ops.leafify(df) — drop Depth-hierarchy ancestor rows.\n"
    "- helpers.charts.waterfall(labels, values, title)/ranked_bar(labels, "
    "values, title)/evolution(x, y, title, ylabel) -> styled figures "
    "(labels/values/x/y are LISTS, not frames).\n"
    "- section(title, table=, chart=, full=False): attach an artifact to a "
    "report section (full=True for extractions renders EVERY row in the UI); "
    "attached tables are echoed back to you — use their values in the note."
)


def run(session, code: str) -> str:
    """Execute `code` in the persistent namespace; return stdout/error text."""
    session.code_log.append(code)
    stdout = io.StringIO()

    def _exec():
        with contextlib.redirect_stdout(stdout):
            exec(code, session.namespace)  # noqa: S102 — deliberate, see module docstring

    try:
        _, elapsed = timed(_exec)
    except Exception:
        error = traceback.format_exc(limit=3)
        session.trace.append(Step(kind="tool", name="run_python", status="failed",
                                  summary=error.strip().splitlines()[-1],
                                  detail={"code": code, "error": error}))
        return (f"CODE FAILED:\n{error}\nFix the code and run again "
                f"(the namespace is unchanged up to the failing line's effects).")

    output = stdout.getvalue()
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + f"\n... (truncated at {MAX_OUTPUT_CHARS} chars)"
    session.trace.append(Step(kind="tool", name="run_python",
                              summary=(output.strip().splitlines() or ["(no output)"])[0][:200],
                              detail={"code": code}, elapsed_ms=elapsed))
    return output or "(no output — print() what you need to see)"
