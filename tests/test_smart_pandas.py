import matplotlib
matplotlib.use("Agg")  # headless backend for tests, no display needed

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from mrx.pipeline_errors import AnswerError
from mrx.smart_pandas import ask
from tests.conftest import FakeChatLLM

DF = pd.DataFrame({"value": [1, 2, 3, 4]})


def test_happy_path_returns_number_result_narration_method_and_code():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "ANSWER: The average value is 2.5.\nMETHOD: Averaged the value column.",
    ])
    result = ask(DF, "What is the average value?", llm)
    assert result.type == "number"
    assert result.value == 2.5
    assert result.narration == "The average value is 2.5."
    assert result.method == "Averaged the value column."
    assert 'df["value"].mean()' in result.code


def test_dataframe_typed_result():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "dataframe", "value": df[df["value"] > 2]}\n```',
        "ANSWER: Two rows have a value greater than 2.\nMETHOD: Filtered rows where value > 2.",
    ])
    result = ask(DF, "Show rows where value > 2", llm)
    assert result.type == "dataframe"
    assert list(result.value["value"]) == [3, 4]
    assert result.narration == "Two rows have a value greater than 2."
    assert result.method == "Filtered rows where value > 2."


def test_retries_after_a_failing_attempt():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["nonexistent_col"].mean()}\n```',
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "ANSWER: The average value is 2.5.\nMETHOD: Averaged the value column.",
    ])
    result = ask(DF, "What is the average value?", llm)
    assert result.value == 2.5
    # 2 code-gen attempts + 1 narration call = 3 total invocations.
    assert len(llm.calls) == 3
    # The code exposed on the result is the winning attempt, not the failed one.
    assert "nonexistent_col" not in result.code


def test_gives_up_after_max_attempts():
    llm = FakeChatLLM(["not valid python at all !!!"])
    with pytest.raises(AnswerError):
        ask(DF, "irrelevant", llm, max_attempts=3)


def test_chart_typed_result_returns_a_figure():
    llm = FakeChatLLM([
        (
            '```python\n'
            'fig, ax = plt.subplots()\n'
            'ax.plot(df["value"])\n'
            'ax.set_title("Value over index")\n'
            'result = {"type": "chart", "value": fig}\n'
            '```'
        ),
        "ANSWER: This chart shows value rising across the index.\nMETHOD: Plotted value against its index.",
    ])
    result = ask(DF, "Plot the value", llm)
    assert result.type == "chart"
    assert isinstance(result.value, plt.Figure)
    assert result.narration == "This chart shows value rising across the index."
    assert result.method == "Plotted value against its index."


def test_chart_narration_describes_axes_not_the_figure_object():
    llm = FakeChatLLM([
        (
            '```python\n'
            'fig, ax = plt.subplots()\n'
            'ax.plot(df["value"])\n'
            'ax.set_title("My Chart")\n'
            'ax.set_xlabel("Index")\n'
            'ax.set_ylabel("Value")\n'
            'result = {"type": "chart", "value": fig}\n'
            '```'
        ),
        "ANSWER: narration\nMETHOD: method",
    ])
    ask(DF, "Plot the value", llm)
    narration_prompt = llm.calls[1][1].content  # second invoke() call, HumanMessage
    assert "My Chart" in narration_prompt
    assert "Index" in narration_prompt
    assert "Value" in narration_prompt


def test_stray_figures_are_closed_leaving_only_the_returned_one():
    llm = FakeChatLLM([
        (
            '```python\n'
            'plt.figure()  # a stray figure the code doesn\'t return\n'
            'fig, ax = plt.subplots()\n'
            'ax.plot(df["value"])\n'
            'result = {"type": "chart", "value": fig}\n'
            '```'
        ),
        "ANSWER: narration\nMETHOD: method",
    ])
    result = ask(DF, "Plot the value", llm)
    assert plt.get_fignums() == [plt.figure(result.value.number).number]


def test_narration_failure_falls_back_to_plain_value_and_empty_method():
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
    assert result.method == ""


def test_narration_response_missing_the_expected_format_falls_back_gracefully():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "just a plain sentence, no structured markers at all",
    ])
    result = ask(DF, "What is the average value?", llm)
    assert result.narration == "just a plain sentence, no structured markers at all"
    assert result.method == ""


def test_original_query_is_surfaced_to_code_gen_when_it_differs_from_the_question():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "ANSWER: 2.5\nMETHOD: averaged",
    ])
    ask(
        DF, "Show the average value", llm,
        original_query="Plot the evolution of the value",
    )
    code_gen_prompt = llm.calls[0][1].content  # first invoke() call, HumanMessage
    assert "Plot the evolution of the value" in code_gen_prompt


def test_original_query_not_repeated_when_identical_to_the_question():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "ANSWER: 2.5\nMETHOD: averaged",
    ])
    ask(DF, "What is the average value?", llm, original_query="What is the average value?")
    code_gen_prompt = llm.calls[0][1].content
    assert code_gen_prompt.count("What is the average value?") == 1


def test_no_original_query_falls_back_to_question_only():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "ANSWER: 2.5\nMETHOD: averaged",
    ])
    ask(DF, "What is the average value?", llm)  # no original_query passed
    code_gen_prompt = llm.calls[0][1].content
    assert "original wording" not in code_gen_prompt


def test_narration_mentioning_the_word_answer_mid_sentence_does_not_false_match():
    # "ANSWER:" only counts when it starts a line — otherwise a response that
    # happens to use the word mid-sentence could be mis-parsed (regression
    # test for exactly that bug).
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "The answer: 2.5, computed with no METHOD: field present.",
    ])
    result = ask(DF, "What is the average value?", llm)
    assert result.narration == "The answer: 2.5, computed with no METHOD: field present."
    assert result.method == ""
