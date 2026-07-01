import pandas as pd
import pytest

from mrx import orchestrator
from mrx.generate_link import MRXPlan
from mrx.pipeline_errors import PlanGenerationError, PlanValidationError
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
    defaults = dict(
        intent="test", view_reasoning="r", parameters="p", assumptions=[],
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


def test_full_pipeline_happy_path(monkeypatch, fake_pymrx):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    result = orchestrator.run(_answer_llm(), "irrelevant, get_link is stubbed")

    assert result.df.shape == (3, 1)
    assert result.answer.value == 20.0
    assert result.attempts == 1


def test_original_user_query_reaches_the_answer_stage_as_a_safety_net(monkeypatch, fake_pymrx):
    # orchestrator.run must pass the user's ORIGINAL query (not just plan.SmartDF)
    # into smart_pandas.ask, so a rephrasing that drops intent (e.g. "plot" ->
    # "show") can't fully erase it before the answer stage sees it.
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    plan = _plan(SmartDF="Show the average value")  # rephrasing dropped "plot the evolution of"
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: plan)

    llm = _answer_llm()
    orchestrator.run(llm, "Plot the evolution of the value")

    first_call_prompt = llm.calls[0][1].content  # first invoke() call, HumanMessage
    assert "Plot the evolution of the value" in first_call_prompt


def test_on_stage_callback_fires_once_per_stage_in_order(monkeypatch, fake_pymrx):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    stages = []
    orchestrator.run(_answer_llm(), "irrelevant", on_stage=stages.append)

    assert stages == ["plan", "fetch", "answer"]


def test_on_stage_is_optional(monkeypatch, fake_pymrx):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    # Must not raise when on_stage is omitted (the default None path).
    orchestrator.run(_answer_llm(), "irrelevant")


def test_on_token_reaches_the_answer_stage(monkeypatch, fake_pymrx):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    seen = []
    orchestrator.run(_answer_llm(), "irrelevant", on_token=seen.append)

    assert len(seen) > 0  # smart_pandas.ask actually received and used the callback


def test_plan_retry_recovers_from_validation_error(monkeypatch, fake_pymrx):
    fake_pymrx["df"] = pd.DataFrame({"value": [1, 2, 3]})
    bad_plan = _plan(url=VALID_URL.replace("p13=EQDELTACASH", "p13=MADE_UP_CODE"))
    good_plan = _plan()

    calls = {"n": 0}

    def fake_get_link(llm, query, **kw):
        calls["n"] += 1
        return bad_plan if calls["n"] == 1 else good_plan

    monkeypatch.setattr(orchestrator.generate_link, "get_link", fake_get_link)

    result = orchestrator.run(_answer_llm(), "irrelevant")
    assert result.attempts == 2
    assert calls["n"] == 2


def test_exhausting_retries_raises_plan_validation_error(monkeypatch, fake_pymrx):
    bad_plan = _plan(url=VALID_URL.replace("p13=EQDELTACASH", "p13=STILL_BAD"))
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: bad_plan)

    with pytest.raises(PlanValidationError):
        orchestrator.run(object(), "irrelevant", max_attempts=3)


def test_get_link_failure_is_wrapped_as_plan_generation_error(monkeypatch, fake_pymrx):
    def broken_get_link(llm, query, **kw):
        raise FileNotFoundError("mrx_manual.md missing")

    monkeypatch.setattr(orchestrator.generate_link, "get_link", broken_get_link)

    with pytest.raises(PlanGenerationError):
        orchestrator.run(object(), "irrelevant", max_attempts=1)
