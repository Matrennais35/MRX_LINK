"""The free-form pandas exec sandbox — the Analyst agent's FALLBACK when the
tested analysis toolkit doesn't cover a question.

Ported as-is from the proven implementation. Trust model (deliberate, not an
oversight): the LLM prompt and the dataframes are both internal, so generated
code runs via exec() with no OS-level sandbox; if that trust boundary ever
changes (untrusted questions or data), this needs a real sandbox.

The result contract: generated code assigns `result = {"type": ..., "value":
...}`; charts must be live matplotlib Figures (a common LLM mistake is
returning the Axes — caught here and routed into the corrective retry loop
rather than crashing downstream).
"""

from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

import re


def _extract_code(response_text: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", response_text, re.DOTALL)
    code = match.group(1) if match else response_text
    return code.strip()


# Matches the Streamlit UI's dark-terminal theme (see .streamlit/config.toml)
# so charts don't render as a jarring white rectangle in an otherwise dark
# app. Applied to every generated chart regardless of what the LLM's code
# does, since the LLM has no reason to know the app's color scheme.
_CHART_STYLE = {
    "figure.facecolor": "#141619",
    "axes.facecolor": "#141619",
    "axes.edgecolor": "#2A2E33",
    "axes.labelcolor": "#C9CDD3",
    "text.color": "#C9CDD3",
    "xtick.color": "#6B7280",
    "ytick.color": "#6B7280",
    "grid.color": "#2A2E33",
    "axes.prop_cycle": plt.cycler(color=["#E8A33D", "#6B7280", "#C9CDD3"]),
    "font.family": "monospace",
}


def _run_code(code: str, datasets: dict) -> Any:
    # matplotlib's pyplot state is global (figures persist across exec() calls
    # in the same process), so start from a clean slate — otherwise a stray
    # figure from a prior question could leak into an unrelated result, or
    # accumulate in memory across a long-running Streamlit session.
    plt.close("all")

    namespace = {**datasets, "pd": pd, "plt": plt}
    with plt.rc_context(_CHART_STYLE):
        exec(code, namespace)
    if "result" not in namespace:
        raise ValueError("code did not assign a `result` variable")

    result = namespace["result"]
    if result.get("type") == "chart":
        wanted = _validated_figure(result.get("value"))
        _close_other_figures(wanted)
    elif result.get("type") == "composed":
        wanted = _validate_composed(result.get("value"))
        # `wanted` is the composed chart Figure (or None if the composed
        # result is table-only) — close any stray figures around it.
        _close_other_figures(wanted)

    return result


def _validated_figure(value: Any) -> "plt.Figure":
    """Return `value` iff it's a live matplotlib Figure, else raise.

    An easy, plausible LLM mistake is assigning the Axes instead of the Figure
    (the prompt's example does `fig, ax = plt.subplots()`, so confusing which
    to return is a one-word typo away). Catching it here routes the mistake
    through the corrective-retry loop instead of crashing later in app.py's
    st.pyplot(), which sits outside PipelineError handling.
    """
    if not isinstance(value, plt.Figure) or value.number not in plt.get_fignums():
        raise ValueError(
            f"a chart value must be a live matplotlib Figure (e.g. the `fig` from "
            f"`fig, ax = plt.subplots()`), got {type(value).__name__}"
        )
    return value


def _close_other_figures(keep) -> None:
    """Close every open figure except `keep` (may be None), so an answer can't
    carry along or leak other figures the code created."""
    for num in plt.get_fignums():
        fig = plt.figure(num)
        if fig is not keep:
            plt.close(fig)


def _validate_composed(value: Any):
    """Validate a composed result's value dict, returning its chart Figure (or
    None if table-only). A composed answer is a dict with at least one of a
    DataFrame `table` or a Figure `chart` — the narrative is written separately
    by the synthesis step (see synthesize()), NOT by the code-gen, so it's not
    required here.
    """
    if not isinstance(value, dict):
        raise ValueError(f"a composed result's value must be a dict, got {type(value).__name__}")

    table = value.get("table")
    chart = value.get("chart")
    if table is None and chart is None:
        raise ValueError("a composed result must have at least one of 'table' or 'chart'")
    if table is not None and not isinstance(table, pd.DataFrame):
        raise ValueError(f"a composed result's 'table' must be a DataFrame or None, got {type(table).__name__}")
    extra = value.get("tables")
    if extra is not None:
        if not isinstance(extra, dict) or not all(
            isinstance(k, str) and isinstance(v, pd.DataFrame) for k, v in extra.items()
        ):
            raise ValueError("a composed result's 'tables' must be a dict of name -> DataFrame")

    return _validated_figure(chart) if chart is not None else None


# =============================================================================
# The generate-and-run fallback loop (agents propose the request; this executes)
# =============================================================================

CODEGEN_SYSTEM_PROMPT = """\
You compute a requested result over pandas DataFrame(s) by writing Python code.

Rules:
- The named DataFrame(s) below, `pd` (pandas), and `plt` (matplotlib.pyplot)
  are already available; do not import anything.
- Compute FROM the given data — never hardcode a value you can only get by
  reading the printed schema/sample rows.
- Prefer vectorized pandas (groupby/agg/masks) over row loops.
- A frame may be "wide" (dates as columns, e.g. "2026-06-01", ...): for a
  trend over time, melt to long format first so dates become the x-axis.
- Assign the final result to `result`, one of:
  - result = {"type": "number", "value": <int or float>}
  - result = {"type": "string", "value": "<short prose>"}
  - result = {"type": "dataframe", "value": <a pandas DataFrame>}
  - result = {"type": "chart", "value": <a live matplotlib Figure (the `fig`
    from fig, ax = plt.subplots())>}
  - result = {"type": "composed", "value": {"table": <DataFrame or None>,
    "chart": <Figure or None>,
    "tables": {"<name>": <DataFrame>, ...}}}   # "tables" is OPTIONAL: extra
    prepared/intermediate tables, each registered as an evidence dataset under
    its name so subsequent toolkit operations can reference it. "table" is the
    PRIMARY result table; at least one of table/chart must be present.
- Return ONLY a single ```python fenced code block. No prose outside it.
"""


def describe_datasets(datasets: dict) -> str:
    """Columns/dtypes + first rows per named frame, for the codegen prompt."""
    chunks = []
    for name, df in datasets.items():
        chunks.append(
            f"`{name}`:\nColumns and dtypes:\n{df.dtypes.to_string()}\n\n"
            f"First rows:\n{df.head(5).to_string()}"
        )
    return "\n\n".join(chunks)


def generate_and_run(llm, datasets: dict, request: str, *, max_attempts: int = 3) -> dict:
    """Generate pandas code for `request` over the named `datasets`, execute it
    in the sandbox, and return the validated {"type", "value"} result — with
    the executed code under the "code" key for the audit trail. Failures are
    fed back for correction up to `max_attempts` tries, then re-raised.
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=CODEGEN_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Available data:\n{describe_datasets(datasets)}\n\n"
            f"Compute this: {request}"
        )),
    ]
    last_error = None
    for attempt in range(1, max_attempts + 1):
        response_text = llm.invoke(messages).content
        code = _extract_code(response_text)
        try:
            result = _run_code(code, datasets)
            result["code"] = code
            return result
        except Exception as e:
            last_error = e
            if attempt == max_attempts:
                break
            messages.append(AIMessage(content=response_text))
            messages.append(HumanMessage(content=(
                f"That code failed: {e}\n"
                "Fix it and return a corrected ```python``` block that still "
                "assigns `result` in the required shape."
            )))
    raise ValueError(f"codegen failed after {max_attempts} attempts: {last_error}")
