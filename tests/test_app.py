"""End-to-end tests for app.py's chat UI, using Streamlit's AppTest to run
the real script. The fake LLM must answer the per-step StepDecision call as well as the
planning and answer calls.
"""

from dataclasses import dataclass, field

import pytest
from streamlit.testing.v1 import AppTest

from mrx.pipeline.models import MRXPlan

APP_PATH = "app.py"

VALID_URL = (
    "https://market.risk.echonet/Market%20Risk%20Explorer/Market%20Risk%20Explorer.application"
    "?env=Production&viewid=6168&p1=EQDUSNLH&p1021=Current&p1029=Total"
    "&p1217=RowGrpRiskType&p1175=Usable&p1131=No+tracking&p1133=Perimeter+Completion"
    "&p27=2024-11-01&p28=2024-10-31&p13=EQDELTACASH"
)


@dataclass
class _Msg:
    content: str


class _Wrapper:
    def __init__(self, value):
        self._value = value

    def invoke(self, messages):
        return self._value


class _FakeLLM:
    """Drives app_v2.py through a full loop run: one fetch step, then an
    answer step, then the pandas-code + narration calls. `step_actions` lets
    a test script a specific sequence of StepDecision actions.
    """

    def __init__(self, step_actions=None):
        self._plan = MRXPlan(
            intent="test view", view_reasoning="r", parameters="p", assumptions=[],
            confidence=0.95, needs_clarification=None, SmartDF="What is the average value?",
            url=VALID_URL,
        )
        # Default: fetch once, then answer — the minimal real loop.
        self._step_actions = list(step_actions) if step_actions else ["fetch", "answer"]

    def with_structured_output(self, schema):
        if schema.__name__ == "StepDecision":
            action = self._step_actions.pop(0) if len(self._step_actions) > 1 else self._step_actions[0]
            return _Wrapper(schema(
                action=action,
                reasoning="DESK_A dominates so drilling in" if action == "fetch" else "gathered enough",
                fetch_query="FX Vega by desk" if action == "fetch" else "",
            ))
        return _Wrapper(self._plan)  # MRXPlan for get_link

    def invoke(self, messages):
        text = str(messages[-1].content) if messages else ""
        if "Computed value" in text or "explain a computed answer" in text.lower():
            return _Msg("ANSWER: The average value is 20.\nMETHOD: Computed the mean of the value column.")
        return _Msg('```python\nresult = {"type": "number", "value": df["value"].mean()}\n```')

    def stream(self, messages):
        content = self.invoke(messages).content
        chunk_size = max(1, len(content) // 4)
        for i in range(0, len(content), chunk_size):
            yield _Msg(content[i:i + chunk_size])


@pytest.fixture(autouse=True)
def fake_pipeline(monkeypatch, tmp_catalog, fake_pymrx):
    import pandas as pd
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})

    from mrx.pipeline import connect_llm
    monkeypatch.setattr(connect_llm, "get_llm", lambda model, version: _FakeLLM())

    import streamlit as st
    st.cache_resource.clear()


def test_initial_load_shows_chat_input_and_examples():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)

    assert not at.exception
    assert len(at.chat_input) == 1
    assert "c" in at.query_params


def test_asking_a_question_renders_a_full_turn_with_the_answer():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What is the average value?").run(timeout=30)

    assert not at.exception
    assert len(at.chat_message) == 2  # user + assistant

    all_text = " ".join(m.value for cm in at.chat_message for m in cm.markdown)
    assert "What is the average value?" in all_text
    assert "The average value is 20." in all_text


def test_investigation_trace_is_shown_with_the_step_reasoning():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("analyse FX Vega").run(timeout=30)

    assert not at.exception
    # The trace expander renders each step's reasoning — the headline view.
    all_markdown = " ".join(
        m.value for cm in at.chat_message for m in cm.markdown
    )
    assert "DESK_A dominates" in all_markdown  # the fetch step's reasoning
    assert "Step 1" in all_markdown and "Step 2" in all_markdown


def test_status_box_is_fully_cleared_after_a_successful_answer():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What is the average value?").run(timeout=30)

    assert not at.exception
    assert len(at.status) == 0


def test_step_trace_is_persisted_and_reloads_with_the_conversation():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("analyse FX Vega").run(timeout=30)
    # AppTest.query_params returns a list per key (Streamlit QueryParams
    # semantics), so index [0] for the scalar conversation id.
    conversation_id = at.query_params["c"]
    if isinstance(conversation_id, list):
        conversation_id = conversation_id[0]

    # The trace was written to the catalog under the turn — reopening the
    # conversation in a fresh AppTest (new process state) must reload it.
    from mrx.pipeline import catalog
    turns = catalog.list_turns(conversation_id=conversation_id)
    assert len(turns) == 1
    steps = catalog.list_steps(turn_id=turns[0].id)
    assert [s.action for s in steps] == ["fetch", "answer"]
    assert any("DESK_A dominates" in s.reasoning for s in steps)
