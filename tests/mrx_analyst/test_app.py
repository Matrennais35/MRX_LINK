"""End-to-end AppTest coverage for analyst_app.py (the rebuild's UI)."""

import matplotlib
matplotlib.use("Agg")

import pytest
from streamlit.testing.v1 import AppTest

from tests.mrx_analyst.test_orchestrator import (
    FakeLLM, FakeView, _attribution_spec, _fetch_plan, _passing_critique, _plan,
)

APP_PATH = "analyst_app.py"


@pytest.fixture(autouse=True)
def fake_app_backend(monkeypatch):
    """A FakeView (no pymrx) + per-test LLM injection + cache clearing."""
    from mrx_analyst.core import orchestrator
    monkeypatch.setattr(orchestrator, "DEFAULT_VIEW", FakeView())

    import streamlit as st
    st.cache_resource.clear()


def _install_llm(monkeypatch, llm):
    from mrx_analyst.common import llm as llm_factory
    monkeypatch.setattr(llm_factory, "get_llm", lambda model, version, **kw: llm)


def _data_llm():
    return FakeLLM(structured={
        "AnalysisPlan": [_plan()],
        "MultiFetchPlan": [_fetch_plan(n=1)],
        "AnalysisSpec": [_attribution_spec("view_0")],
        "Critique": [_passing_critique()],
    }, texts=["Book A drove the move, partly offset by B."])


def test_initial_load_shows_chat_input_and_mints_a_conversation(monkeypatch):
    _install_llm(monkeypatch, _data_llm())
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    assert not at.exception
    assert len(at.chat_input) == 1
    assert "c" in at.query_params


def test_full_data_turn_renders_narrative_table_plan_and_trace(monkeypatch):
    _install_llm(monkeypatch, _data_llm())
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("what drove the move?").run(timeout=30)

    assert not at.exception
    all_markdown = " ".join(m.value for cm in at.chat_message for m in cm.markdown)
    assert "Book A drove the move" in all_markdown          # the narrative
    assert len(at.dataframe) >= 1                            # the facts table
    labels = [e.label or "" for e in at.expander]
    assert any("How the assistant approached" in l for l in labels)   # the plan
    assert any("Trace" in l for l in labels)                          # the trace
    assert any("feedback" in l.lower() for l in labels)               # feedback form


def test_respond_short_circuit_renders_prose_only(monkeypatch):
    llm = FakeLLM(structured={"AnalysisPlan": [_plan(needs_data=False)]},
                  texts=["A direct summary of the conversation."])
    _install_llm(monkeypatch, llm)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("summarise").run(timeout=30)

    assert not at.exception
    all_markdown = " ".join(m.value for cm in at.chat_message for m in cm.markdown)
    assert "A direct summary" in all_markdown
    assert len(at.dataframe) == 0                            # no table for prose


def test_turn_replays_after_reload_with_persisted_trace(monkeypatch):
    _install_llm(monkeypatch, _data_llm())
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("what drove the move?").run(timeout=30)
    conversation_id = at.query_params["c"]
    if isinstance(conversation_id, list):
        conversation_id = conversation_id[0]

    at2 = AppTest.from_file(APP_PATH)
    at2.query_params["c"] = conversation_id
    at2.run(timeout=30)
    assert not at2.exception
    all_markdown = " ".join(m.value for cm in at2.chat_message for m in cm.markdown)
    assert "Book A drove the move" in all_markdown           # narrative replayed
    labels = [e.label or "" for e in at2.expander]
    assert any("Trace" in l for l in labels)                 # persisted trace replayed
