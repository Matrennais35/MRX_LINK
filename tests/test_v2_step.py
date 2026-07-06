"""Tests for the V2 per-step decision (mrx.pipeline.v2.step)."""

import pandas as pd

from mrx.pipeline.v2 import step
from mrx.pipeline.v2.step import StepDecision
from tests.conftest import FakeStructuredLLM


def test_first_step_summary_says_nothing_fetched_yet():
    # The first step has no gathered data; the prompt must make that explicit
    # so the model knows it has to fetch (there's nothing to answer from).
    assert "nothing fetched yet" in step._describe_gathered([])


def test_gathered_summary_lists_each_frame_label_columns_and_sample():
    df = pd.DataFrame({"desk": ["DESK_A", "DESK_B"], "fx_vega": [900, 120]})
    summary = step._describe_gathered([("FX Vega by desk", df)])

    assert "FX Vega by desk" in summary
    assert "desk" in summary and "fx_vega" in summary  # columns line
    assert "DESK_A" in summary  # sample rows included


def test_gathered_summary_does_not_dump_the_whole_frame():
    # Only a small head() sample belongs in the prompt, not every row — the
    # model decides the next step from shape + a glance, same stance as
    # router/smart_pandas description helpers.
    df = pd.DataFrame({"deal": [f"D{i}" for i in range(50)], "v": range(50)})
    summary = step._describe_gathered([("many deals", df)])

    assert "D0" in summary
    assert "D49" not in summary  # tail rows must not be in the summary


def test_decide_next_step_returns_the_llms_structured_decision():
    fake = FakeStructuredLLM([
        StepDecision(action="fetch", reasoning="need by-desk first", fetch_query="FX Vega by desk"),
    ])

    decision = step.decide_next_step(fake, "analyse FX Vega variation", gathered=[])

    assert decision.action == "fetch"
    assert decision.fetch_query == "FX Vega by desk"


def test_decide_next_step_can_choose_to_answer_with_empty_fetch_query():
    fake = FakeStructuredLLM([
        StepDecision(action="answer", reasoning="by-desk data is enough", fetch_query=""),
    ])
    df = pd.DataFrame({"desk": ["DESK_A"], "fx_vega": [900]})

    decision = step.decide_next_step(fake, "which desk has most FX Vega", gathered=[("by desk", df)])

    assert decision.action == "answer"
    assert decision.fetch_query == ""


def test_decide_next_step_passes_gathered_data_into_the_prompt():
    # The gathered-so-far summary must actually reach the model, otherwise it
    # can't make an after-seeing-data decision (the whole point of V2).
    fake = FakeStructuredLLM([
        StepDecision(action="answer", reasoning="enough", fetch_query=""),
    ])
    df = pd.DataFrame({"desk": ["DESK_A"], "fx_vega": [900]})

    step.decide_next_step(fake, "q", gathered=[("FX Vega by desk", df)])

    human_message = fake.calls[0][1].content
    assert "FX Vega by desk" in human_message
    assert "DESK_A" in human_message
