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

    `route_modes`, if given, is a list of RoutingDecision.mode values
    consumed one per call to route() (i.e. one per question asked) —
    lets a test simulate the router choosing "answer_from_context" on a
    follow-up after "single_fetch" on the first question, the way the real
    router would once this conversation has context. Defaults to always
    "single_fetch" (every existing test's assumption, unchanged).
    """

    def __init__(self, route_modes=None):
        self._plan = MRXPlan(
            intent="test", view_reasoning="r", parameters="p", assumptions=[],
            confidence=0.95, needs_clarification=None, SmartDF="What is the average value?",
            url=VALID_URL,
        )
        self._route_modes = list(route_modes) if route_modes else ["single_fetch"]

    def with_structured_output(self, schema):
        if schema.__name__ == "RoutingDecision":
            mode = self._route_modes.pop(0) if len(self._route_modes) > 1 else self._route_modes[0]
            return _Wrapper(schema(mode=mode, reasoning="r", new_view_queries=[] if mode == "answer_from_context" else ["q"]))
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

    # app.py's get_llm() is @st.cache_resource-decorated. That cache is
    # process-global, not scoped to one AppTest instance — without
    # clearing it here, a test whose monkeypatched connect_llm.get_llm
    # differs from a PRIOR test's (e.g. a test using a _BrokenLLM to
    # simulate a failure) can silently reuse the previous test's cached
    # _FakeLLM instance instead of its own, since @st.cache_resource has
    # no way to know the underlying factory changed between tests.
    import streamlit as st
    st.cache_resource.clear()


def _use_route_modes(monkeypatch, route_modes):
    # Overrides the autouse fake_pipeline fixture's plain _FakeLLM() with
    # one that walks through a specific sequence of router.route() modes —
    # used only by tests that need the router to behave differently across
    # successive questions in the same conversation (e.g. single_fetch then
    # answer_from_context). st.cache_resource means app.py's get_llm() only
    # calls this factory once per AppTest session, so the same _FakeLLM
    # instance (and its route_modes list) persists across reruns.
    from mrx.pipeline import connect_llm
    monkeypatch.setattr(connect_llm, "get_llm", lambda model, version: _FakeLLM(route_modes=route_modes))


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


def test_status_box_is_fully_cleared_after_a_successful_answer():
    # Regression test: st.status() on its own only ever collapses to a
    # small "Done" pill — it can never fully disappear from the page. That
    # pill was accumulating in the thread on every single past turn,
    # confirmed clutter distinct from any scroll/overlap issue. A
    # successful turn's status indicator must be gone entirely, not just
    # collapsed, once the answer is on screen.
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What is the average value?").run(timeout=30)

    assert not at.exception
    assert len(at.status) == 0


def test_status_box_stays_visible_after_a_failed_answer(monkeypatch):
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
    assert len(at.status) == 1
    assert at.status[0].label == "Failed"
    assert at.status[0].state == "error"


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

    new_chat_button = next(b for b in at.button if b.label == "+ New chat")
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


def test_sidebar_lists_past_conversations():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What is the average value?").run(timeout=30)
    # The sidebar renders before the query-handling block that saves this
    # turn (top-to-bottom script execution within one rerun), so the new
    # conversation only appears in the list starting the NEXT rerun — an
    # empty chat_input submission is a convenient no-op rerun trigger here.
    at.run(timeout=30)

    assert not at.exception
    # Each conversation renders its question preview as markdown text
    # inside a bordered container (see app.py's sidebar block), not a
    # button label.
    sidebar_text = [m.value for m in at.sidebar.markdown]
    assert any("What is the average value?" in text for text in sidebar_text)


def test_sidebar_truncates_a_long_question():
    long_question = "What is the average EQ PV Diff between 2026-05-30 and 2026-06-03 for US_SPX in GLEQD, broken down by desk and product?"
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value(long_question).run(timeout=30)
    at.run(timeout=30)

    assert not at.exception
    sidebar_text = [m.value for m in at.sidebar.markdown]
    truncated = next((text for text in sidebar_text if long_question[:20] in text), None)
    assert truncated is not None
    assert "..." in truncated
    assert len(truncated) < len(long_question)


def test_clicking_a_sidebar_conversation_switches_to_it():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("first conversation question").run(timeout=30)
    # dict(at.query_params)["c"] is a list (QueryParams supports multi-
    # valued params) — take the single value for use in a widget key.
    first_conv_id = dict(at.query_params)["c"][0]

    # Start a new chat, ask something else — a second, distinct conversation.
    new_chat_button = next(b for b in at.button if b.label == "+ New chat")
    new_chat_button.click().run(timeout=30)
    at.chat_input[0].set_value("second conversation question").run(timeout=30)
    # Same top-to-bottom-execution note as test_sidebar_lists_past_conversations:
    # the sidebar needs one more rerun to reflect this just-saved turn, and
    # only then will the (now inactive) first conversation show its "Open" button.
    at.run(timeout=30)

    assert not at.exception
    # The first conversation is now inactive, so it should render an "Open"
    # button — find it via its widget key, which embeds the conversation id
    # (app.py's key is f"conv_{conversation_id}", and conversation_id
    # already starts with "conv_" — so the full key has that prefix twice).
    switch_button = next(
        b for b in at.sidebar.button
        if b.key == f"conv_{first_conv_id}"
    )
    switch_button.click().run(timeout=30)

    assert not at.exception
    assert dict(at.query_params)["c"][0] == first_conv_id
    all_text = " ".join(m.value for cm in at.chat_message for m in cm.markdown)
    assert "first conversation question" in all_text
    assert "second conversation question" not in all_text


def test_sidebar_shows_recently_fetched_datasets():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What is the average value?").run(timeout=30)
    at.run(timeout=30)  # same top-to-bottom ordering note as the test above

    assert not at.exception
    sidebar_text = " ".join(m.value for m in at.sidebar.markdown)
    # _FakeLLM's plan has intent="test" — see the Dataset.description field,
    # which orchestrator.py sets from plan.intent.
    assert "test" in sidebar_text


def test_followup_question_answers_from_context_instead_of_refetching(monkeypatch):
    # The actual bug this was all built to fix: "from this data, what was
    # the biggest daily variation" was triggering a brand-new MRX fetch
    # instead of analyzing the chart's already-fetched data. Simulates the
    # router correctly recognizing the follow-up (mode="answer_from_context"
    # on the second question) and asserts app.py's conversation_id wiring
    # actually gets that far — no new fetch happens for the follow-up.
    _use_route_modes(monkeypatch, ["single_fetch", "answer_from_context"])

    fetch_calls = {"n": 0}
    from mrx.pipeline import data_fetch
    real_fetch = data_fetch.fetch_data

    def counting_fetch(url):
        fetch_calls["n"] += 1
        return real_fetch(url)

    monkeypatch.setattr(data_fetch, "fetch_data", counting_fetch)

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What is the average value?").run(timeout=30)
    assert not at.exception
    assert fetch_calls["n"] == 1

    at.chat_input[0].set_value("What was the biggest daily variation?").run(timeout=30)

    assert not at.exception
    assert fetch_calls["n"] == 1  # unchanged — the follow-up did not trigger a new fetch
    all_text = " ".join(m.value for cm in at.chat_message for m in cm.markdown)
    assert "What was the biggest daily variation?" in all_text


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
