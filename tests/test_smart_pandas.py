import matplotlib
matplotlib.use("Agg")  # headless backend for tests, no display needed

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from mrx.pipeline.pipeline_errors import AnswerError
from mrx.pipeline.smart_pandas import ask, sanitize_names
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


def test_on_token_streams_the_code_gen_and_narration_responses():
    code_response = '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```'
    narration_response = "ANSWER: The average value is 2.5.\nMETHOD: Averaged the value column."
    llm = FakeChatLLM([code_response, narration_response])

    seen = []
    result = ask(DF, "What is the average value?", llm, on_token=seen.append)

    assert result.value == 2.5
    # The callback is invoked incrementally, and its final call for each
    # streamed response equals the full response text.
    assert seen[-1] == narration_response
    code_gen_calls = [b for b in seen if b in code_response or code_response.startswith(b)]
    assert any(b == code_response for b in seen)
    assert len(seen) > 2  # more than one accumulation step happened, i.e. it's incremental


def test_on_token_buffer_resets_between_retry_attempts():
    bad_code = '```python\nresult = {"type": "number", "value": df["nonexistent_col"].mean()}\n```'
    good_code = '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```'
    narration = "ANSWER: 2.5\nMETHOD: averaged"
    llm = FakeChatLLM([bad_code, good_code, narration])

    seen = []
    ask(DF, "What is the average value?", llm, on_token=seen.append)

    # The bad attempt's full text must appear (it did stream), but the
    # buffer must not concatenate bad_code + good_code together — each
    # attempt's accumulation is its own, separate buffer.
    assert bad_code in seen
    assert good_code in seen
    assert (bad_code + good_code) not in seen


def test_no_on_token_uses_plain_invoke_and_is_unaffected():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "ANSWER: 2.5\nMETHOD: averaged",
    ])
    result = ask(DF, "What is the average value?", llm)  # no on_token
    assert result.value == 2.5


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


def test_composed_result_returns_narrative_table_and_chart():
    # A composed analytical answer carries a narrative + table + chart together.
    llm = FakeChatLLM([
        (
            '```python\n'
            'fig, ax = plt.subplots()\n'
            'ax.bar(["a", "b"], [3, 1])\n'
            'tbl = pd.DataFrame({"item": ["a", "b"], "value": [3, 1]})\n'
            'result = {"type": "composed", "value": {\n'
            '    "narrative": "The total is 4; item a drove +3.",\n'
            '    "table": tbl,\n'
            '    "chart": fig,\n'
            '}}\n'
            '```'
        ),
        # NOTE: no narration response needed — composed skips the narration call.
    ])
    result = ask(DF, "analyse what drove the total", llm)

    assert result.type == "composed"
    assert result.value["narrative"] == "The total is 4; item a drove +3."
    assert isinstance(result.value["table"], pd.DataFrame)
    assert isinstance(result.value["chart"], plt.Figure)
    # The narrative passes through as the answer's narration (no re-narration).
    assert result.narration == "The total is 4; item a drove +3."


def test_composed_result_does_not_call_the_narration_llm():
    # The narrative is written by the code-gen step; the separate narration
    # call must NOT run (proven by giving the LLM exactly ONE response — a
    # narration call would try to pop a second and fail differently).
    llm = FakeChatLLM([
        (
            '```python\n'
            'tbl = pd.DataFrame({"x": [1]})\n'
            'result = {"type": "composed", "value": {"narrative": "n", "table": tbl, "chart": None}}\n'
            '```'
        ),
    ])
    result = ask(DF, "analyse it", llm)
    assert result.type == "composed"
    assert len(llm.calls) == 1  # code-gen only, no narration call


def test_composed_with_neither_table_nor_chart_is_rejected_and_retried():
    # A composed result must have at least one artifact — else it's just a
    # string answer. An empty one should trigger the corrective-retry loop.
    empty_composed = (
        '```python\n'
        'result = {"type": "composed", "value": {"narrative": "n", "table": None, "chart": None}}\n'
        '```'
    )
    good = (
        '```python\n'
        'result = {"type": "composed", "value": {'
        '"narrative": "n", "table": pd.DataFrame({"x":[1]}), "chart": None}}\n'
        '```'
    )
    llm = FakeChatLLM([empty_composed, good])
    result = ask(DF, "analyse it", llm)
    assert result.type == "composed"
    assert result.value["table"] is not None


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


def test_chart_result_holding_axes_instead_of_figure_triggers_a_retry_not_a_crash():
    # Regression test: an easy LLM mistake (given the prompt's own
    # `fig, ax = plt.subplots()` example) is assigning the Axes instead of
    # the Figure to result["value"]. This must be caught and fed back for
    # correction, not silently accepted only to crash downstream (e.g.
    # app.py's st.pyplot() call, which sits outside error handling).
    llm = FakeChatLLM([
        '```python\nfig, ax = plt.subplots()\nax.plot(df["value"])\nresult = {"type": "chart", "value": ax}\n```',
        '```python\nfig, ax = plt.subplots()\nax.plot(df["value"])\nresult = {"type": "chart", "value": fig}\n```',
        "ANSWER: narration\nMETHOD: method",
    ])
    result = ask(DF, "Plot the value", llm)
    assert result.type == "chart"
    assert isinstance(result.value, plt.Figure)
    # 2 code-gen attempts (first rejected, second corrected) + 1 narration call.
    assert len(llm.calls) == 3


def test_chart_result_with_non_figure_value_exhausts_retries_cleanly():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "chart", "value": "not a figure at all"}\n```',
    ])
    with pytest.raises(AnswerError):
        ask(DF, "Plot the value", llm, max_attempts=2)


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


def test_narration_failure_falls_back_to_a_labeled_plain_value_and_empty_method():
    # Regression test: this used to fall back to a bare str(value) (just
    # "2.5"), which was indistinguishable in the UI from the LLM
    # deliberately answering with no explanation — the user had no way to
    # tell narration had actually failed. The fallback must say so.
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
    assert "2.5" in result.narration
    assert "no narration" in result.narration.lower()
    assert result.method == ""


def test_narration_response_missing_the_expected_format_falls_back_gracefully():
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "just a plain sentence, no structured markers at all",
    ])
    result = ask(DF, "What is the average value?", llm)
    assert result.narration == "just a plain sentence, no structured markers at all"
    assert result.method == ""


def test_narration_with_a_well_formed_but_blank_answer_line_falls_back_to_labeled_value():
    # Regression test: a syntactically valid "ANSWER: \nMETHOD: ..."
    # response (the LLM answered the format correctly but left the answer
    # itself empty) is NOT an exception anywhere in the call chain — it
    # used to sail through as an empty-string narration, which app.py
    # renders as literally nothing: a bare number/chart with no
    # explanation, indistinguishable from the LLM deliberately being
    # terse. Must fall back the same way an actual failure does.
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "ANSWER: \nMETHOD: Averaged the value column.",
    ])
    result = ask(DF, "What is the average value?", llm)
    assert "2.5" in result.narration
    assert "no narration" in result.narration.lower()
    assert result.method == "Averaged the value column."


def test_narration_failure_on_a_chart_result_does_not_stringify_the_figure():
    # Regression test: the fallback narration must go through
    # _describe_value (title/axis labels), not str(value) directly —
    # str() on a matplotlib Figure produces an unhelpful repr like
    # "Figure(640x480)", which would be actively misleading shown as a
    # "narration" in place of an actual explanation.
    class NarrationFailsLLM:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return type("R", (), {
                    "content": (
                        '```python\n'
                        'fig, ax = plt.subplots()\n'
                        'ax.plot(df["value"])\n'
                        'ax.set_title("My Chart")\n'
                        'result = {"type": "chart", "value": fig}\n'
                        '```'
                    )
                })()
            raise RuntimeError("narration model unavailable")

    result = ask(DF, "Plot the value", NarrationFailsLLM())
    assert "My Chart" in result.narration
    assert "Figure(" not in result.narration


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


def test_multiple_named_datasets_are_all_available_to_generated_code():
    by_desk = pd.DataFrame({"desk": ["EQ", "FX"], "vega": [100, 200]})
    by_product = pd.DataFrame({"product": ["Option", "Swap"], "vega": [150, 150]})
    llm = FakeChatLLM([
        '```python\n'
        'total = fx_vega_by_desk["vega"].sum() + fx_vega_by_product["vega"].sum()\n'
        'result = {"type": "number", "value": total}\n'
        '```',
        "ANSWER: The combined total is 600.\nMETHOD: Summed both breakdowns.",
    ])
    result = ask(
        {"fx_vega_by_desk": by_desk, "fx_vega_by_product": by_product},
        "combine both breakdowns", llm,
    )
    assert result.value == 600


def test_multi_dataset_system_prompt_describes_every_frame_by_name():
    a = pd.DataFrame({"x": [1]})
    b = pd.DataFrame({"y": [2]})
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": 1}\n```',
        "ANSWER: 1\nMETHOD: m",
    ])
    ask({"frame_a": a, "frame_b": b}, "irrelevant", llm)
    code_gen_prompt = llm.calls[0][1].content
    assert "frame_a" in code_gen_prompt
    assert "frame_b" in code_gen_prompt


def test_single_dataframe_still_normalizes_to_df_variable_name():
    # Backward-compatible path: a bare DataFrame (not a dict) is still
    # exposed as `df`, matching every pre-multi-dataset caller/test.
    llm = FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "ANSWER: 2.5\nMETHOD: averaged",
    ])
    result = ask(DF, "what is the average", llm)
    assert result.value == 2.5


def test_sanitize_names_produces_valid_python_identifiers():
    result = sanitize_names({"FX Vega (by desk)!": pd.DataFrame(), "Plain": pd.DataFrame()})
    assert set(result.keys()) == {"fx_vega_by_desk", "plain"}


def test_sanitize_names_disambiguates_collisions_deterministically():
    result = sanitize_names({
        "FX Vega (by desk)": pd.DataFrame({"a": [1]}),
        "FX Vega — by desk!": pd.DataFrame({"a": [2]}),
    })
    assert len(result) == 2
    names = list(result.keys())
    assert names[0] == "fx_vega_by_desk"
    assert names[1] == "fx_vega_by_desk_2"
    # Both dataframes are preserved, not one overwriting the other.
    assert result["fx_vega_by_desk"]["a"].iloc[0] == 1
    assert result["fx_vega_by_desk_2"]["a"].iloc[0] == 2


def test_sanitize_names_handles_a_label_starting_with_a_digit():
    result = sanitize_names({"2026 FX Vega": pd.DataFrame()})
    name = list(result.keys())[0]
    assert not name[0].isdigit()
    assert name.isidentifier()


def test_sanitize_names_never_drops_a_dataframe_even_with_a_three_way_collision():
    # Regression test: a counter-only disambiguation scheme could produce
    # the SAME final name for two different inputs when one label naturally
    # sanitizes to what a counter-suffixed name would also produce (e.g.
    # "fx_vega_2" reached both by a repeated "fx vega" label's second
    # occurrence AND by a distinct label that IS "fx vega 2"). This silently
    # dropped a dataframe. All three distinct inputs must survive.
    result = sanitize_names([
        ("FX Vega!", pd.DataFrame({"a": [1]})),
        ("FX Vega?", pd.DataFrame({"a": [2]})),
        ("FX  Vega 2", pd.DataFrame({"a": [3]})),
    ])
    assert len(result) == 3
    values = sorted(df["a"].iloc[0] for df in result.values())
    assert values == [1, 2, 3]


def test_sanitize_names_accepts_a_list_of_pairs_with_duplicate_labels():
    # A dict can't represent duplicate keys at all — sanitize_names must
    # accept an iterable of (label, df) pairs so two views sharing the
    # exact same label (e.g. identical LLM-written `intent`) both survive,
    # rather than the caller building a dict first and silently losing one.
    result = sanitize_names([
        ("FX Vega by desk", pd.DataFrame({"a": [1]})),
        ("FX Vega by desk", pd.DataFrame({"a": [2]})),
    ])
    assert len(result) == 2
    values = sorted(df["a"].iloc[0] for df in result.values())
    assert values == [1, 2]


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
