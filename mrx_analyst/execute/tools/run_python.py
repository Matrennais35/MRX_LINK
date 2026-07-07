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

MAX_OUTPUT_CHARS = 4000

TOOL_DESCRIPTION = (
    "Run Python over the fetched dataframes (they are in the namespace under "
    "their registered labels). Available: pd, np, plt, helpers (tested ops: "
    "helpers.ops.trend/attribution/variance/concentration/position_change — "
    "all Depth-hierarchy-safe — and helpers.charts.waterfall/ranked_bar/"
    "evolution), and section(title, table=, chart=) to attach an artifact to "
    "a report section. The namespace PERSISTS across calls. print() what you "
    "need to see; the output comes back to you."
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
