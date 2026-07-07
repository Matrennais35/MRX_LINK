"""AppTest coverage for analyst_app.py on the v3 engine (design->execute->write)."""

import matplotlib
matplotlib.use("Agg")

import pytest
from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest

from mrx_analyst.design.blueprint import Blueprint, FetchSpec, SectionSpec
from mrx_analyst.mrx.models import MRXPlan
from mrx_analyst.write.critic import Critique
from tests.mrx_analyst.conftest import VALID_URL, FakeView
from tests.mrx_analyst.test_slice import FakeSliceLLM, _tc

APP_PATH = "analyst_app.py"

REPORT = """FX Vega rose 750, driven by Book A.

## Drivers
Book A +900, Book B -150 offset.
"""


def _blueprint():
    return Blueprint(
        target="what drove it",
        sections=[SectionSpec(title="Drivers", must_establish="signed attribution",
                              data_needed="by-book cut", artifact="ranked bar + table")],
        fetches=[FetchSpec(request="by-book cut", when="now")],
    )


def _mrx_plan():
    return MRXPlan(intent="overview", view_reasoning="r", parameters="p", assumptions=[],
                   confidence=0.95, needs_clarification=None, SmartDF="q",
                   url=VALID_URL.format(risk="EQDELTACASH"))


def _app_llm():
    return FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()],
                    "Critique": [Critique(verdict="pass", issues=[])]},
        script=[
            AIMessage(content="", tool_calls=[_tc("fetch_mrx", {"request": "cut"}, "c1")]),
            AIMessage(content="", tool_calls=[_tc("run_python", {"code": (
                "section('Drivers', table=overview)")}, "c2")]),
            AIMessage(content=REPORT, tool_calls=[]),
        ],
    )


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch):
    from mrx_analyst import run as runner
    monkeypatch.setattr(runner, "DEFAULT_VIEW", FakeView())
    import streamlit as st
    st.cache_resource.clear()


def _install_llm(monkeypatch, llm):
    from mrx_analyst.common import llm as llm_factory
    monkeypatch.setattr(llm_factory, "get_llm", lambda model, version, **kw: llm)


def test_initial_load_shows_chat_input_and_mints_a_conversation(monkeypatch):
    _install_llm(monkeypatch, _app_llm())
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    assert not at.exception
    assert len(at.chat_input) == 1
    assert "c" in at.query_params


def test_full_turn_renders_note_sections_blueprint_and_feedback(monkeypatch):
    _install_llm(monkeypatch, _app_llm())
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("what drove the move?").run(timeout=30)

    assert not at.exception
    all_markdown = " ".join(m.value for cm in at.chat_message for m in cm.markdown)
    assert "FX Vega rose 750" in all_markdown              # the note's summary
    assert "Book A +900" in all_markdown                   # the section text
    assert len(at.dataframe) >= 1                          # the section table
    labels = [e.label or "" for e in at.expander]
    assert any("blueprint" in l.lower() for l in labels)   # the design, reviewable
    assert any("Trace" in l for l in labels)
    assert any("feedback" in l.lower() for l in labels)


def test_clarification_renders_as_a_question(monkeypatch):
    llm = FakeSliceLLM(
        structured={"Blueprint": [Blueprint(target="?", clarification="Which measure do you mean?")]},
        script=[],
    )
    _install_llm(monkeypatch, llm)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("analyse it").run(timeout=30)
    assert not at.exception
    all_markdown = " ".join(m.value for cm in at.chat_message for m in cm.markdown)
    assert "Which measure do you mean?" in all_markdown


def test_turn_replays_after_reload(monkeypatch):
    _install_llm(monkeypatch, _app_llm())
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
    assert "FX Vega rose 750" in all_markdown              # narrative replayed
