"""Tests for the per-step decision (mrx.pipeline.step)."""

import pandas as pd

from mrx.pipeline import step
from mrx.pipeline.step import AnalysisPlan, StepDecision
from tests.conftest import FakeStructuredLLM


def test_plan_analysis_returns_the_structured_plan():
    plan = AnalysisPlan(
        target="which book drove the FX Vega increase",
        approach="net move, then by-book, then drill into the top book",
        representation="contribution waterfall",
        success_criteria="names the dominant driver and flags concentration",
    )
    llm = FakeStructuredLLM([plan])

    result = step.plan_analysis(llm, "what drove the FX Vega increase?")

    assert result.target == "which book drove the FX Vega increase"
    assert result.representation == "contribution waterfall"


def test_plan_is_threaded_into_the_step_decision_prompt():
    # The decision must SEE the plan, so each step is argued against the target.
    decision = StepDecision(action="fetch", reasoning="r", fetch_query="q")
    llm = FakeStructuredLLM([decision])
    plan = AnalysisPlan(
        target="THE-TARGET", approach="THE-APPROACH",
        representation="waterfall", success_criteria="THE-CRITERIA",
    )

    step.decide_next_step(llm, "q", gathered=[], history=(), plan=plan)

    prompt = llm.calls[0][1].content
    assert "THE-TARGET" in prompt
    assert "THE-APPROACH" in prompt
    assert "THE-CRITERIA" in prompt


def test_step_decision_without_a_plan_reads_as_before():
    # A trivial path (no plan) must not inject an empty plan block.
    decision = StepDecision(action="respond", reasoning="r")
    llm = FakeStructuredLLM([decision])

    step.decide_next_step(llm, "q", gathered=[], history=(), plan=None)

    prompt = llm.calls[0][1].content
    assert "Analysis plan:" not in prompt


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


def test_decide_next_step_can_choose_to_analyze_with_empty_fetch_query():
    fake = FakeStructuredLLM([
        StepDecision(action="analyze", reasoning="by-desk data is enough", fetch_query=""),
    ])
    df = pd.DataFrame({"desk": ["DESK_A"], "fx_vega": [900]})

    decision = step.decide_next_step(fake, "which desk has most FX Vega", gathered=[("by desk", df)])

    assert decision.action == "analyze"
    assert decision.fetch_query == ""


def test_decide_next_step_passes_gathered_data_into_the_prompt():
    # The gathered-so-far summary must actually reach the model, otherwise it
    # can't make an after-seeing-data decision (the whole point of the loop).
    fake = FakeStructuredLLM([
        StepDecision(action="analyze", reasoning="enough", fetch_query=""),
    ])
    df = pd.DataFrame({"desk": ["DESK_A"], "fx_vega": [900]})

    step.decide_next_step(fake, "q", gathered=[("FX Vega by desk", df)])

    human_message = fake.calls[0][1].content
    assert "FX Vega by desk" in human_message
    assert "DESK_A" in human_message
