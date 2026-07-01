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
from typing import Any

import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .pipeline_errors import AnswerError

SYSTEM_PROMPT = """\
You answer questions about a pandas DataFrame called `df` by writing Python code.

Rules:
- `df` and `pd` (pandas) are already available; do not import anything.
- Write code that computes the answer FROM `df` — never hardcode a value you
  can only get by reading the printed schema/sample rows.
- Assign the final answer to a variable named `result`, using this shape:
  - result = {"type": "string", "value": "<a short prose answer>"}
  - result = {"type": "number", "value": <int or float>}
  - result = {"type": "dataframe", "value": <a pandas DataFrame>}
- Return ONLY a single ```python fenced code block. No prose outside it.
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
    namespace = {"df": df, "pd": pd}
    exec(code, namespace)
    if "result" not in namespace:
        raise ValueError("code did not assign a `result` variable")
    return namespace["result"]


@dataclass
class AnswerResult:
    type: str
    value: Any


def ask(df: pd.DataFrame, question: str, llm, *, max_attempts: int = 3) -> AnswerResult:
    """Answer a natural-language question about `df` using `llm`.

    On a code-generation or execution failure, the error and the offending
    code are sent back to the LLM as a correction request, up to
    `max_attempts` tries, before raising AnswerError.
    """
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"{_describe_df(df)}\n\nQuestion: {question}"),
    ]

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        response = llm.invoke(messages)
        code = _extract_code(response.content)

        try:
            result = _run_code(code, df)
            return AnswerResult(type=result.get("type", "string"), value=result.get("value"))
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
