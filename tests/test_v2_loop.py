"""Tests for the V2 bounded controller loop (mrx.pipeline.v2.loop).

These assert INVARIANTS (never exceed the fetch cap, every fetch was
validation-gated, the loop always terminates, the count is model-driven) —
not the exact fixed fetch counts V1's tests assert, since a model-driven loop
makes the count variable by design (see docs/agent_loop_design.md).
"""

import pandas as pd
import pytest

from mrx.pipeline import orchestrator
from mrx.pipeline.v2 import loop
from mrx.pipeline.v2.step import StepDecision
from mrx.pipeline.pipeline_errors import AnswerError
from tests.conftest import FakeChatLLM

VALID_URL = (
    "https://market.risk.echonet/Market%20Risk%20Explorer/Market%20Risk%20Explorer.application"
    "?env=Production&viewid=6168&p1=EQDUSNLH&p1021=Current&p1029=Total"
    "&p1217=RowGrpRiskType&p1175=Usable&p1131=No+tracking&p1133=Perimeter+Completion"
    "&p27=2024-11-01&p28=2024-10-31&p13=EQDELTACASH"
    "&p1073=CMRC%2cMetier%2cActivity%2cLocal-V%26RC%2cLocal-RiskIM"
    "&p1016=Full+Tenors&p1201=Fixed+Tenors&p1370=Raw+Data&p1031=None&p1011=And"
    "&p1169=Standard&p1160=Y&p1144=BNP+Paribas+view+(market+risk)"
)


def _plan(**overrides):
    from mrx.pipeline.models import MRXPlan
    defaults = dict(
        intent="test view", view_reasoning="r", parameters="p", assumptions=[],
        confidence=0.95, needs_clarification=None, SmartDF="What is the average value?",
        url=VALID_URL,
    )
    defaults.update(overrides)
    return MRXPlan(**defaults)


def _answer_llm():
    return FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "The average value is what it is.",
    ])


def _script_decisions(monkeypatch, decisions):
    """Make decide_next_step return `decisions` in order (one per loop step).
    Also spies the gathered-so-far passed in, so tests can assert the loop
    feeds accumulated data back into each decision.
    """
    seen_gathered = []
    seq = list(decisions)

    def fake_decide(llm, query, gathered):
        seen_gathered.append(list(gathered))
        return seq.pop(0)

    monkeypatch.setattr(loop, "decide_next_step", fake_decide)
    return seen_gathered


@pytest.fixture
def stub_planning(monkeypatch):
    """Every fetch plans via the real _get_view -> generate_link.get_link;
    stub get_link so it doesn't need a real LLM, but leave validation.validate_plan
    REAL (the URL above is valid) so the gate genuinely runs on every fetch.
    """
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())


@pytest.fixture
def stub_answer(monkeypatch):
    """Stub the answer stage for loop-invariant tests: they assert HOW the
    loop gathered/capped/recorded, not the correctness of generated pandas
    code over N sanitized frames (that's covered by smart_pandas' own tests).
    Isolating the answer stage keeps these tests about the loop, and immune
    to how many frames end up named `df` vs a sanitized identifier.
    """
    from mrx.pipeline import smart_pandas
    from mrx.pipeline.smart_pandas import AnswerResult

    def fake_ask(data, question, llm, **kw):
        return AnswerResult(type="string", value="ok", narration="ok", method="m", code="c")

    monkeypatch.setattr(loop.smart_pandas, "ask", fake_ask)


def test_single_fetch_then_answer_gathers_one_view_and_answers(monkeypatch, fake_pymrx, stub_planning):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning="need the data", fetch_query="FX Vega by desk"),
        StepDecision(action="answer", reasoning="that's enough"),
    ])

    result = loop.run_agent_loop(_answer_llm(), "what's the average")

    assert len(result.views) == 1
    assert result.answer.value == 20.0
    assert [s.action for s in result.steps] == ["fetch", "answer"]


def test_never_exceeds_max_fetches_even_if_model_keeps_asking(monkeypatch, fake_pymrx, stub_planning, stub_answer):
    # The model ALWAYS wants to fetch — the cap, not the model, must stop it.
    fake_pymrx["df"] = pd.DataFrame({"value": [1, 2, 3]})
    always_fetch = [
        StepDecision(action="fetch", reasoning=f"more {i}", fetch_query=f"cut {i}")
        for i in range(20)
    ]
    _script_decisions(monkeypatch, always_fetch)

    result = loop.run_agent_loop(_answer_llm(), "q", max_fetches=3)

    fetches_that_ran = [s for s in result.steps if s.action == "fetch" and not s.capped]
    assert len(fetches_that_ran) == 3
    assert len(result.views) == 3
    # The step where the cap fired is recorded as capped, not silently dropped.
    assert any(s.capped for s in result.steps)


def test_capped_run_still_produces_an_answer_over_what_was_gathered(monkeypatch, fake_pymrx, stub_planning):
    fake_pymrx["df"] = pd.DataFrame({"value": [4, 8]})
    _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning="1", fetch_query="a"),
        StepDecision(action="fetch", reasoning="2", fetch_query="b"),
    ])

    result = loop.run_agent_loop(_answer_llm(), "q", max_fetches=1)

    assert len(result.views) == 1  # cap of 1 honored
    assert result.answer is not None  # still answered, didn't error out


def test_loop_always_terminates_at_max_steps(monkeypatch, fake_pymrx, stub_planning, stub_answer):
    # Even with max_fetches high, max_steps bounds total iterations so the
    # loop can never run forever.
    fake_pymrx["df"] = pd.DataFrame({"value": [1]})
    _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning=str(i), fetch_query=str(i)) for i in range(100)
    ])

    result = loop.run_agent_loop(_answer_llm(), "q", max_fetches=50, max_steps=3)

    assert len(result.steps) <= 3


def test_every_fetch_went_through_the_validation_gate(monkeypatch, fake_pymrx, stub_planning):
    # A model-chosen fetch must still be validated. Stub get_link to return a
    # plan whose URL FAILS validation, and assert the loop surfaces the
    # validation error rather than fetching an unvalidated URL.
    from mrx.pipeline.pipeline_errors import PlanValidationError
    bad_plan = _plan(url="https://evil.example/not-mrx")
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: bad_plan)
    fake_pymrx["df"] = pd.DataFrame({"value": [1]})
    _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning="go", fetch_query="anything"),
        StepDecision(action="answer", reasoning="done"),
    ])

    # _plan_and_validate raises PlanValidationError after max_attempts — the
    # gate ran and rejected the URL; no unvalidated fetch happened.
    with pytest.raises(PlanValidationError):
        loop.run_agent_loop(_answer_llm(), "q", max_attempts=1)


def test_model_answering_immediately_with_no_data_raises_a_clean_error(monkeypatch, fake_pymrx, stub_planning):
    # If the model says "answer" on step 1 with nothing fetched, there's
    # nothing to answer from — must be a caught PipelineError, not a crash.
    _script_decisions(monkeypatch, [
        StepDecision(action="answer", reasoning="I'll just answer"),
    ])

    with pytest.raises(AnswerError):
        loop.run_agent_loop(_answer_llm(), "q")


def test_each_decision_sees_the_data_gathered_so_far(monkeypatch, fake_pymrx, stub_planning, stub_answer):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    seen = _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning="first", fetch_query="a"),
        StepDecision(action="fetch", reasoning="second", fetch_query="b"),
        StepDecision(action="answer", reasoning="enough"),
    ])

    loop.run_agent_loop(_answer_llm(), "q", max_fetches=5)

    # Step 1 saw nothing; step 2 saw the first view; step 3 saw both.
    assert seen[0] == []
    assert len(seen[1]) == 1
    assert len(seen[2]) == 2


def test_step_reasoning_is_threaded_into_the_gathered_frame_label(monkeypatch, fake_pymrx, stub_planning, stub_answer):
    # The provenance fix: a gathered frame's label must include WHY it was
    # fetched, so a later decision (and the answer stage) can relate frames.
    fake_pymrx["df"] = pd.DataFrame({"value": [1, 2]})
    seen = _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning="DESK_A dominates so drill in", fetch_query="DESK_A by deal"),
        StepDecision(action="fetch", reasoning="second", fetch_query="b"),
        StepDecision(action="answer", reasoning="done"),
    ])

    loop.run_agent_loop(_answer_llm(), "q", max_fetches=5)

    # By step 2, the first frame's label carries its fetch reasoning.
    first_label = seen[1][0][0]
    assert "fetched because" in first_label
    assert "DESK_A dominates" in first_label
