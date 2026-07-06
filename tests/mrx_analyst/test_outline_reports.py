"""The outline spine (structure-first reports): the Planner's outline threads
through every stage, section-tagged artifacts land in their sections, an
unfilled section is a VISIBLE gap, and the Narrator's report splits cleanly.
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd

from mrx_analyst.agents.analyst import AnalysisSpec, ToolkitCall
from mrx_analyst.agents.planner import AnalysisPlan, SectionSpec
from mrx_analyst.core import orchestrator
from mrx_analyst.storage import catalog
from tests.mrx_analyst.test_orchestrator import (
    FakeLLM, FakeView, _fetch_plan, _mrx_plan, _passing_critique,
)

OUTLINE = [
    SectionSpec(title="The path", section_question="when did the move happen?",
                needs="daily series", artifact="line chart"),
    SectionSpec(title="Drivers", section_question="which book drove it?",
                needs="attribution by book", artifact="ranked bar + table"),
    SectionSpec(title="Context", section_question="is this big?",
                needs="baseline history", artifact="none"),
]


def _plan_with_outline():
    return AnalysisPlan(
        target="the driver", approach="path then drivers",
        representation="report", success_criteria="names the driver",
        needs_data=True, fetch_goals=["overview"], outline=OUTLINE,
    )


REPORT_MD = """FX Vega rose 7.3m, driven by Book A.

## The path
Two dated step-ups, 24-Jun and 01-Jul.

## Drivers
Book A +900k, Book B -150k offset.
"""


def _sectioned_llm():
    return FakeLLM(structured={
        "AnalysisPlan": [_plan_with_outline()],
        "MultiFetchPlan": [_fetch_plan(n=1)],
        "AnalysisSpec": [AnalysisSpec(reasoning="r", ops=[
            ToolkitCall(tool="attribution", section="Drivers",
                        args_json='{"dataset": "view_0", "group_cols": ["Book"]}'),
            ToolkitCall(tool="ranked_bar_chart", section="Drivers",
                        args_json='{"dataset": "facts", "label_col": "Book", "value_col": "contribution"}'),
        ])],
        "Critique": [_passing_critique()],
    }, texts=[REPORT_MD])


def test_report_split_summary_and_sections():
    summary, texts = orchestrator._split_report(REPORT_MD)
    assert summary == "FX Vega rose 7.3m, driven by Book A."
    assert texts["the path"].startswith("Two dated step-ups")
    assert texts["drivers"].startswith("Book A +900k")


def test_report_split_degrades_to_whole_text_summary():
    summary, texts = orchestrator._split_report("just one blob, no headings")
    assert summary == "just one blob, no headings"
    assert texts == {}


def test_full_sectioned_turn_assembles_the_report():
    result = orchestrator.run_turn(_sectioned_llm(), "what drove it",
                                   session_id="s", view=FakeView())
    answer = result.answer
    # executive summary extracted, sections in outline order
    assert answer.narrative == "FX Vega rose 7.3m, driven by Book A."
    assert [s.title for s in answer.sections] == ["The path", "Drivers", "Context"]
    # section-tagged artifacts landed in THEIR section
    drivers = answer.sections[1]
    assert drivers.status == "filled"
    assert drivers.table is not None and drivers.chart is not None
    assert drivers.text.startswith("Book A +900k")
    # 'The path' got narrator text (filled) even though nothing was computed for it
    assert answer.sections[0].status == "filled" and answer.sections[0].chart is None


def test_unfilled_section_is_a_visible_gap_with_a_reason():
    result = orchestrator.run_turn(_sectioned_llm(), "what drove it",
                                   session_id="s", view=FakeView())
    context = result.answer.sections[2]     # nothing computed, no narrator text
    assert context.status == "unfilled"
    assert "baseline history" in context.reason   # says WHAT was needed


def test_outline_threads_into_scout_analyst_and_narrator_prompts():
    llm = _sectioned_llm()
    orchestrator.run_turn(llm, "what drove it", session_id="s", view=FakeView())
    scout_prompt = next(m for n, m in llm.structured_calls if n == "MultiFetchPlan")[-1].content
    assert "REPORT OUTLINE" in scout_prompt and "The path" in scout_prompt
    analyst_prompt = next(m for n, m in llm.structured_calls if n == "AnalysisSpec")[-1].content
    assert "REPORT OUTLINE" in analyst_prompt and "Drivers" in analyst_prompt
    critic_prompt = next(m for n, m in llm.structured_calls if n == "Critique")[-1].content
    assert "PER-SECTION QUESTIONS" in critic_prompt


def test_all_report_charts_are_persisted_and_reload_in_order(tmp_catalog):
    catalog.save_turn_image("t1", b"png0", index=0)
    catalog.save_turn_image("t1", b"png1", index=1)
    assert catalog.load_turn_images("t1") == [b"png0", b"png1"]
    assert catalog.load_turn_image("t1") == b"png0"    # legacy single still works
    assert catalog.load_turn_images("t_none") == []


def test_plan_without_outline_keeps_the_simple_answer_shape():
    from tests.mrx_analyst.test_orchestrator import _attribution_spec, _plan
    llm = FakeLLM(structured={
        "AnalysisPlan": [_plan()],                     # no outline
        "MultiFetchPlan": [_fetch_plan(n=1)],
        "AnalysisSpec": [_attribution_spec("view_0")],
        "Critique": [_passing_critique()],
    })
    result = orchestrator.run_turn(llm, "q", session_id="s", view=FakeView())
    assert result.answer.sections == []                 # legacy path untouched
    assert result.answer.table is not None
