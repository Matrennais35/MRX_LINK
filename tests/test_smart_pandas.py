import pandas as pd
import pytest

from mrx.pipeline_errors import AnswerError
from mrx.smart_pandas import ask
from tests.conftest import FakeChatLLM

DF = pd.DataFrame({"value": [1, 2, 3, 4]})


def test_happy_path_returns_number_result():
    llm = FakeChatLLM(['```python\nresult = {"type": "number", "value": df["value"].mean()}\n```'])
    result = ask(DF, "What is the average value?", llm)
    assert result.type == "number"
    assert result.value == 2.5


def test_dataframe_typed_result():
    llm = FakeChatLLM(
        ['```python\nresult = {"type": "dataframe", "value": df[df["value"] > 2]}\n```']
    )
    result = ask(DF, "Show rows where value > 2", llm)
    assert result.type == "dataframe"
    assert list(result.value["value"]) == [3, 4]


def test_retries_after_a_failing_attempt():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["nonexistent_col"].mean()}\n```',
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
    ])
    result = ask(DF, "What is the average value?", llm)
    assert result.value == 2.5
    assert len(llm.calls) == 2


def test_gives_up_after_max_attempts():
    llm = FakeChatLLM(["not valid python at all !!!"])
    with pytest.raises(AnswerError):
        ask(DF, "irrelevant", llm, max_attempts=3)
