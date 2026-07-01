"""
Answer natural-language questions over a pymrx dataframe by having the LLM
write pandas code and executing it directly — no third-party agent framework.

Trust model: the LLM prompt and the dataframe are both internal (our own MRX
data, our own model call), so generated code runs directly via exec() with no
sandbox. This is a deliberate choice, not an oversight: exec() with a stripped
namespace does not meaningfully contain a determined adversary in Python, so
if that trust boundary ever changes (e.g. untrusted questions or untrusted
data sources), this needs a real sandbox, not just a bigger namespace.
"""

import re
from dataclasses import dataclass
from typing import Any, Optional

import matplotlib.pyplot as plt
import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .pipeline_errors import AnswerError

SYSTEM_PROMPT = """\
You answer questions about a pandas DataFrame called `df` by writing Python code.

Rules:
- `df`, `pd` (pandas), and `plt` (matplotlib.pyplot) are already available;
  do not import anything.
- Write code that computes the answer FROM `df` — never hardcode a value you
  can only get by reading the printed schema/sample rows.
- Assign the final answer to a variable named `result`, using this shape:
  - result = {"type": "string", "value": "<a short prose answer>"}
  - result = {"type": "number", "value": <int or float>}
  - result = {"type": "dataframe", "value": <a pandas DataFrame>}
  - result = {"type": "chart", "value": <a matplotlib Figure, e.g. via
    fig, ax = plt.subplots() then plotting on ax>}
- Use "chart" whenever the question asks to see, plot, visualize, or show
  the *evolution/trend* of something over time or across categories — not
  only when it says "plot" literally. A plain single-value or lookup
  question should still use "number", "string", or "dataframe".
- `df` may be in "wide" format: one row per entity, with dates as separate
  columns (e.g. columns named like "2026-06-01", "2026-06-02", ...) instead
  of one row per date. If asked to plot an evolution/trend over time and
  `df` looks like this, first reshape it to long format — e.g.
  `df.melt(id_vars=[<non-date columns>], var_name="date", value_name="value")`
  — so dates become the x-axis, rather than plotting the wide frame directly.
- Return ONLY a single ```python fenced code block. No prose outside it.
"""

NARRATION_SYSTEM_PROMPT = """\
You explain a computed answer to a market-risk question, the way a helpful
analyst would. You are given the question, the code that was run to compute
it, and the computed value. Do not invent context you weren't given.

- If the computed value is a single number or short string: state it
  verbatim, do not recompute or restate it differently.
- If the computed value is a table or a chart: you are given only a
  preview/summary of it, not the full data — do NOT try to reproduce its
  contents (no pasting rows, no listing every column/value). The table or
  chart is already shown to the user separately. Instead, describe in
  plain words what it shows (e.g. "a daily series of X across June" or
  "PV Diff broken down by underlying"), using its shape and the question
  to describe what it represents, not what every cell contains.

Respond in exactly this two-part format, nothing else:

ANSWER: <1-3 sentences giving the answer in prose, no preamble like "Sure,
here's the answer">
METHOD: <1-2 sentences on how the value was derived from the data — e.g.
which column(s), which rows/filter, which operation (average, sum, filter,
etc.)>
"""


def _describe_df(df: pd.DataFrame) -> str:
    return (
        f"Columns and dtypes:\n{df.dtypes.to_string()}\n\n"
        f"First rows:\n{df.head(5).to_string()}"
    )


def _extract_code(response_text: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", response_text, re.DOTALL)
    code = match.group(1) if match else response_text
    return code.strip()


def _run_code(code: str, df: pd.DataFrame) -> Any:
    # matplotlib's pyplot state is global (figures persist across exec() calls
    # in the same process), so start from a clean slate — otherwise a stray
    # figure from a prior question could leak into an unrelated result, or
    # accumulate in memory across a long-running Streamlit session.
    plt.close("all")

    namespace = {"df": df, "pd": pd, "plt": plt}
    exec(code, namespace)
    if "result" not in namespace:
        raise ValueError("code did not assign a `result` variable")

    result = namespace["result"]
    if result.get("type") == "chart":
        # Close every figure except the one being returned, so a chart-typed
        # answer can't accidentally carry along other figures the code
        # created (or leak them once the caller is done with this one).
        wanted = result.get("value")
        for num in plt.get_fignums():
            fig = plt.figure(num)
            if fig is not wanted:
                plt.close(fig)

    return result


@dataclass
class AnswerResult:
    type: str
    value: Any
    narration: str
    method: str
    code: str


def _describe_value(result_type: str, value: Any) -> str:
    """A short, prompt-safe description of the computed value to narrate.

    Dataframe results are summarized (shape + head), never dumped in full —
    both to keep the narration prompt small and because "explain this value"
    doesn't make sense for an arbitrarily large table. Chart results can't be
    stringified meaningfully at all, so they're described by their axis
    labels/title instead of the Figure object itself.
    """
    if result_type == "dataframe":
        return f"a table with shape {value.shape}, first rows:\n{value.head(5).to_string()}"
    if result_type == "chart":
        ax = value.axes[0] if value.axes else None
        title = ax.get_title() if ax else ""
        xlabel = ax.get_xlabel() if ax else ""
        ylabel = ax.get_ylabel() if ax else ""
        return f"a chart titled {title!r} (x: {xlabel!r}, y: {ylabel!r})"
    return str(value)


def _parse_narration_response(text: str, value: Any) -> tuple[str, str]:
    """Split the "ANSWER: ...\nMETHOD: ..." response into (narration, method).

    Only matches ANSWER:/METHOD: at the start of a line, so a response that
    merely mentions those words mid-sentence doesn't false-match. Falls back
    to using the whole response as the narration (and an empty method) if
    the LLM didn't follow the format — narration quality degrading
    gracefully matters more than enforcing a strict format here.
    """
    answer_match = re.search(r"^ANSWER:\s*(.*?)(?=\n^METHOD:|\Z)", text, re.DOTALL | re.MULTILINE)
    method_match = re.search(r"^METHOD:\s*(.*)", text, re.DOTALL | re.MULTILINE)
    if answer_match:
        return answer_match.group(1).strip(), (method_match.group(1).strip() if method_match else "")
    return text.strip() or str(value), ""


def _narrate(question: str, result_type: str, value: Any, code: str, llm) -> tuple[str, str]:
    """Turn a computed value into (narration, method). Never raises — falls
    back to the plain value so a cosmetic step can't lose a correct,
    already-computed answer.
    """
    try:
        response = llm.invoke([
            SystemMessage(content=NARRATION_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Question: {question}\n"
                f"Code that was run:\n{code}\n\n"
                f"Computed value: {_describe_value(result_type, value)}"
            )),
        ])
        return _parse_narration_response(response.content, value)
    except Exception:
        return str(value), ""


def _format_question(question: str, original_query: Optional[str]) -> str:
    """Combine the (possibly rephrased) question with the user's original
    wording, when given. `question` (e.g. plan.SmartDF) may have dropped
    nuance during rephrasing — such as "plot"/"visualize" intent, since
    upstream rephrasing examples skew toward "Show ..." phrasing — so the
    original wording is included as a cross-check, not a replacement.
    """
    if not original_query or original_query.strip() == question.strip():
        return f"Question: {question}"
    return (
        f"Question: {question}\n"
        f"(User's original wording, for context on intent — e.g. if they "
        f"asked to plot/visualize something: {original_query!r})"
    )


def ask(
    df: pd.DataFrame,
    question: str,
    llm,
    *,
    max_attempts: int = 3,
    original_query: Optional[str] = None,
) -> AnswerResult:
    """Answer a natural-language question about `df` using `llm`.

    `question` is typically the planner's rephrased question (e.g.
    plan.SmartDF); `original_query` is the user's own wording, passed as a
    safety net in case the rephrasing dropped intent (see _format_question).

    On a code-generation or execution failure, the error and the offending
    code are sent back to the LLM as a correction request, up to
    `max_attempts` tries, before raising AnswerError. Once a value is
    computed, a second call turns it into a short prose explanation — that
    call narrates the already-computed value, it never recomputes it, so a
    narration failure can't corrupt or lose the answer (it falls back to the
    plain value instead of raising).
    """
    question_block = _format_question(question, original_query)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"{_describe_df(df)}\n\n{question_block}"),
    ]

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        response = llm.invoke(messages)
        code = _extract_code(response.content)

        try:
            result = _run_code(code, df)
            result_type = result.get("type", "string")
            value = result.get("value")
            narration, method = _narrate(question, result_type, value, code, llm)
            return AnswerResult(
                type=result_type, value=value, narration=narration, method=method, code=code
            )
        except Exception as e:
            last_error = e
            if attempt == max_attempts:
                break
            messages.append(AIMessage(content=response.content))
            messages.append(HumanMessage(
                content=(
                    f"That code failed: {e}\n"
                    "Fix it and return a corrected ```python``` block that "
                    "still assigns `result` in the required shape."
                )
            ))

    raise AnswerError(f"Failed to answer question over the data: {last_error}") from last_error
