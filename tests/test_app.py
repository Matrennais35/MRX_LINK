"""End-to-end tests for app.py's chat UI and conversation persistence,
using Streamlit's AppTest to actually run the script (not just import it).

These are the only tests in the suite that exercise app.py directly — the
Streamlit widgets, session_state, and query_params wiring can't be verified
by unit-testing orchestrator.py alone. AppTest.from_file runs the real
script in-process, so `tmp_catalog`'s monkeypatch on mrx.pipeline.catalog
still applies (same module object app.py imports).
"""

from dataclasses import dataclass, field
from typing import Optional

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
class _FakeRoutingDecision:
    mode: str = "single_fetch"
    reasoning: str = "r"
    new_view_queries: list = field(default_factory=list)


class _FakeLLM:
    """A single fake LLM that plausibly answers get_link/route/ask calls,
    good enough to drive app.py through a full run without a real backend.
    Not meant to test pipeline correctness (that's test_orchestrator.py's
    job) — only that app.py wires everything together and renders.
    """

    def __init__(self):
        self._plan = MRXPlan(
            intent="test", view_reasoning="r", parameters="p", assumptions=[],
            confidence=0.95, needs_clarification=None, SmartDF="What is the average value?",
            url=VALID_URL,
        )

    def with_structured_output(self, schema):
        if schema.__name__ == "RoutingDecision":
            return _Wrapper(schema(mode="single_fetch", reasoning="r", new_view_queries=[]))
        return _Wrapper(self._plan)

    def invoke(self, messages):
        text = str(messages[-1].content) if messages else ""
        if "explain a computed answer" in text.lower() or (messages and "Computed value" in str(messages[-1].content)):
            return _Msg("ANSWER: The average value is 20.\nMETHOD: Computed the mean of the value column.")
        return _Msg('```python\nresult = {"type": "number", "value": df["value"].mean()}\n```')

    def stream(self, messages):
        content = self.invoke(messages).content
        chunk_size = max(1, len(content) // 4)
        for i in range(0, len(content), chunk_size):
            yield _Msg(content[i:i + chunk_size])


@dataclass
class _Msg:
    content: str


class _Wrapper:
    def __init__(self, value):
        self._value = value

    def invoke(self, messages):
        return self._value


@pytest.fixture(autouse=True)
def fake_pipeline(monkeypatch, tmp_catalog, fake_pymrx):
    fake_pymrx["df"] = None
    import pandas as pd
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})

    from mrx.pipeline import connect_llm
    monkeypatch.setattr(connect_llm, "get_llm", lambda model, version: _FakeLLM())


def test_initial_load_shows_chat_input_and_examples():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)

    assert not at.exception
    assert len(at.chat_input) == 1
    assert "c" in at.query_params  # a conversation id was minted


def test_asking_a_question_renders_a_full_turn():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What is the average value?").run(timeout=30)

    assert not at.exception
    assert len(at.chat_message) == 2  # user + assistant

    all_text = " ".join(m.value for cm in at.chat_message for m in cm.markdown)
    assert "What is the average value?" in all_text
    assert "The average value is 20." in all_text


def test_multiple_turns_accumulate_in_one_session():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What is the average value?").run(timeout=30)
    at.chat_input[0].set_value("What about again?").run(timeout=30)

    assert not at.exception
    assert len(at.chat_message) == 4  # two full turns, nothing overwritten


def test_conversation_survives_a_simulated_page_refresh():
    # A real browser refresh is: same URL (so same "c" query param), but a
    # brand new script execution with no shared st.session_state. Simulate
    # that with a second, independent AppTest given the first one's
    # conversation id via query_params.
    at1 = AppTest.from_file(APP_PATH)
    at1.run(timeout=30)
    at1.chat_input[0].set_value("What is the average value?").run(timeout=30)
    conv_id = dict(at1.query_params)["c"]

    at2 = AppTest.from_file(APP_PATH)
    at2.query_params["c"] = conv_id
    at2.run(timeout=30)

    assert not at2.exception
    assert len(at2.chat_message) == 2
    all_text = " ".join(m.value for cm in at2.chat_message for m in cm.markdown)
    assert "What is the average value?" in all_text
    assert "The average value is 20." in all_text


def test_different_conversation_ids_do_not_see_each_others_history():
    at1 = AppTest.from_file(APP_PATH)
    at1.run(timeout=30)
    at1.chat_input[0].set_value("What is the average value?").run(timeout=30)

    at2 = AppTest.from_file(APP_PATH)
    at2.run(timeout=30)  # no shared query_params -> a different conversation id

    assert not at2.exception
    assert len(at2.chat_message) == 0
    assert dict(at1.query_params)["c"] != dict(at2.query_params)["c"]


def test_new_chat_button_clears_the_thread_without_deleting_history():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What is the average value?").run(timeout=30)
    old_conv_id = dict(at.query_params)["c"]

    new_chat_button = next(b for b in at.button if b.label == "New chat")
    new_chat_button.click().run(timeout=30)

    assert not at.exception
    assert len(at.chat_message) == 0
    new_conv_id = dict(at.query_params)["c"]
    assert new_conv_id != old_conv_id

    # The old conversation's history must still be reachable, not deleted.
    at_reopened = AppTest.from_file(APP_PATH)
    at_reopened.query_params["c"] = old_conv_id
    at_reopened.run(timeout=30)

    assert not at_reopened.exception
    assert len(at_reopened.chat_message) == 2


def test_a_failed_question_stays_visible_across_the_next_rerun(monkeypatch):
    # Regression test: a failed question used to visibly appear (rendered
    # inline for that one run) and then silently vanish from the thread on
    # the NEXT rerun, because it was never added to st.session_state — only
    # successful turns were. A second, subtler bug found while fixing this:
    # the first fix used isinstance(item, _FailedTurn), which is broken
    # because Streamlit re-executes app.py's source on every rerun,
    # redefining _FailedTurn as a new class object each time — an instance
    # stashed on one rerun fails isinstance() against the next rerun's
    # freshly-defined class. Must be duck-typed (hasattr), not isinstance.
    from mrx.pipeline import connect_llm
    from mrx.pipeline.pipeline_errors import PlanGenerationError

    class _BrokenLLM:
        def with_structured_output(self, schema):
            raise PlanGenerationError("boom")

    monkeypatch.setattr(connect_llm, "get_llm", lambda model, version: _BrokenLLM())

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("a question that will fail").run(timeout=30)

    assert not at.exception
    assert len(at.chat_message) == 2  # the failed question + its error

    # The next rerun (asking anything else) must NOT silently drop it.
    at.chat_input[0].set_value("another question").run(timeout=30)

    assert not at.exception
    assert len(at.chat_message) == 4
    all_text = " ".join(m.value for cm in at.chat_message for m in cm.markdown)
    assert "a question that will fail" in all_text
    assert "another question" in all_text
