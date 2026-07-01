import pandas as pd
import pytest

from mrx.pipeline_errors import AnswerError
from mrx.smart_pandas import ask
from tests.conftest import FakeChatLLM

DF = pd.DataFrame({"value": [1, 2, 3, 4]})


def test_happy_path_returns_number_result_and_narration():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "The average value is 2.5.",
    ])
    result = ask(DF, "What is the average value?", llm)
    assert result.type == "number"
    assert result.value == 2.5
    assert result.narration == "The average value is 2.5."


def test_dataframe_typed_result():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "dataframe", "value": df[df["value"] > 2]}\n```',
        "Two rows have a value greater than 2.",
    ])
    result = ask(DF, "Show rows where value > 2", llm)
    assert result.type == "dataframe"
    assert list(result.value["value"]) == [3, 4]
    assert result.narration == "Two rows have a value greater than 2."


def test_retries_after_a_failing_attempt():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["nonexistent_col"].mean()}\n```',
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "The average value is 2.5.",
    ])
    result = ask(DF, "What is the average value?", llm)
    assert result.value == 2.5
    # 2 code-gen attempts + 1 narration call = 3 total invocations.
    assert len(llm.calls) == 3


def test_gives_up_after_max_attempts():
    llm = FakeChatLLM(["not valid python at all !!!"])
    with pytest.raises(AnswerError):
        ask(DF, "irrelevant", llm, max_attempts=3)


def test_narration_failure_falls_back_to_plain_value():
    class NarrationFailsLLM:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return type("R", (), {
                    "content": '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```'
                })()
            raise RuntimeError("narration model unavailable")

    result = ask(DF, "What is the average value?", NarrationFailsLLM())
    assert result.value == 2.5
    assert result.narration == "2.5"
