import pandas as pd
import pytest

from mrx import catalog, orchestrator, router
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


def test_successful_fetch_is_saved_to_the_catalog(monkeypatch, fake_pymrx, tmp_catalog):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    orchestrator.run(_answer_llm(), "what is the average value", session_id="sess1")

    stored = catalog.list_all(session_id="sess1")
    assert len(stored) == 1
    assert stored[0].session_id == "sess1"
    assert stored[0].query == "what is the average value"
    assert stored[0].plan.url == VALID_URL

    loaded_df = catalog.load_df(stored[0].id)
    assert loaded_df.equals(pd.DataFrame({"value": [10, 20, 30]}))


def test_session_id_is_optional_and_defaults_sensibly(monkeypatch, fake_pymrx, tmp_catalog):
    fake_pymrx["df"] = pd.DataFrame({"value": [1, 2, 3]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    # Must not raise when session_id is omitted (matches main.py's CLI usage).
    orchestrator.run(_answer_llm(), "irrelevant")

    stored = catalog.list_all(session_id=orchestrator.DEFAULT_SESSION_ID)
    assert len(stored) == 1


def test_catalog_save_failure_does_not_break_the_pipeline(monkeypatch, fake_pymrx):
    # If the catalog write fails (e.g. disk full), the user must still get
    # their answer — cataloging is a side effect, not a required stage.
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())
    monkeypatch.setattr(orchestrator.catalog, "save", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))

    result = orchestrator.run(_answer_llm(), "irrelevant")

    assert result.answer.value == 20.0


def test_second_matching_question_reuses_the_first_fetch_without_a_new_call(monkeypatch, fake_pymrx, tmp_catalog):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    fetch_calls = {"n": 0}
    real_fetch = orchestrator.data_fetch.fetch_data

    def counting_fetch(url):
        fetch_calls["n"] += 1
        return real_fetch(url)

    monkeypatch.setattr(orchestrator.data_fetch, "fetch_data", counting_fetch)

    first = orchestrator.run(_answer_llm(), "what is the average value", session_id="sess1")
    second = orchestrator.run(_answer_llm(), "what is the average value again", session_id="sess1")

    assert fetch_calls["n"] == 1  # second call reused, no new MRX fetch
    assert first.reused_dataset_id is None
    assert second.reused_dataset_id is not None
    assert second.df.equals(first.df)


def test_different_dimensions_does_not_reuse(monkeypatch, fake_pymrx, tmp_catalog):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})

    plans = {"n": 0}

    def fake_get_link(llm, query, **kw):
        plans["n"] += 1
        # second question adds a deal-level breakdown not present in the
        # first fetch's row grouping — p1217 stays (mandatory), p1218 is new.
        url = VALID_URL if plans["n"] == 1 else VALID_URL + "&p1218=RowGrpPrdInlNo"
        return _plan(url=url)

    monkeypatch.setattr(orchestrator.generate_link, "get_link", fake_get_link)

    fetch_calls = {"n": 0}
    real_fetch = orchestrator.data_fetch.fetch_data

    def counting_fetch(url):
        fetch_calls["n"] += 1
        return real_fetch(url)

    monkeypatch.setattr(orchestrator.data_fetch, "fetch_data", counting_fetch)

    orchestrator.run(_answer_llm(), "what is the average value", session_id="sess1")
    second = orchestrator.run(_answer_llm(), "split by top deals", session_id="sess1")

    assert fetch_calls["n"] == 2  # different dimensions -> fresh fetch, not reused
    assert second.reused_dataset_id is None


def test_reuse_failure_falls_back_to_a_fresh_fetch(monkeypatch, fake_pymrx, tmp_catalog):
    # If loading a "reusable" dataset fails (e.g. a corrupt/missing parquet
    # file), the pipeline must still answer via a normal fetch, not crash.
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    orchestrator.run(_answer_llm(), "what is the average value", session_id="sess1")
    monkeypatch.setattr(orchestrator.catalog, "load_df", lambda dataset_id: (_ for _ in ()).throw(OSError("corrupt file")))

    result = orchestrator.run(_answer_llm(), "what is the average value again", session_id="sess1")

    assert result.answer.value == 20.0
    assert result.reused_dataset_id is None


def test_allow_multi_fetch_defaults_off_and_route_is_never_called(monkeypatch, fake_pymrx):
    # The redundant-call guard: when allow_multi_fetch is not passed, the
    # router must never be invoked at all — not just "resolve to single".
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())
    monkeypatch.setattr(orchestrator.router, "route", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("route() should not be called")))

    result = orchestrator.run(_answer_llm(), "irrelevant")

    assert result.answer.value == 20.0
    assert result.views is None


def test_multi_fetch_runs_one_get_link_and_fetch_per_view(monkeypatch, fake_pymrx, tmp_catalog):
    view_urls = [
        VALID_URL,
        VALID_URL.replace("p1=EQDUSNLH", "p1=EQDUSNDX") + "&p1218=RowGrpPrdInlNo",
        VALID_URL.replace("p13=EQDELTACASH", "p13=V_GR_EQVEGA_LT"),
    ]
    view_plans = [_plan(url=u, intent=f"view {i}") for i, u in enumerate(view_urls)]

    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query: router.RoutingDecision(
        mode="multi_fetch", reasoning="needs three views",
        new_view_queries=["by desk", "by product", "by deal"],
    ))

    get_link_calls = {"n": 0}

    def fake_get_link(llm, query, **kw):
        plan = view_plans[get_link_calls["n"]]
        get_link_calls["n"] += 1
        return plan

    monkeypatch.setattr(orchestrator.generate_link, "get_link", fake_get_link)

    fetch_calls = {"n": 0}
    dfs = [pd.DataFrame({"value": [1, 2]}), pd.DataFrame({"value": [3, 4]}), pd.DataFrame({"value": [5, 6]})]

    def fake_fetch(url):
        df = dfs[fetch_calls["n"]]
        fetch_calls["n"] += 1
        return df

    monkeypatch.setattr(orchestrator.data_fetch, "fetch_data", fake_fetch)

    seen_datasets = {}

    def fake_ask(data, question, llm, **kw):
        seen_datasets.update(data if isinstance(data, dict) else {"df": data})
        from mrx.smart_pandas import AnswerResult
        return AnswerResult(type="string", value="combined analysis", narration="n", method="m", code="c")

    monkeypatch.setattr(orchestrator.smart_pandas, "ask", fake_ask)

    result = orchestrator.run(
        FakeChatLLM(["irrelevant"]), "analyse the variation by desk, product, and deal",
        allow_multi_fetch=True,
    )

    assert get_link_calls["n"] == 3
    assert fetch_calls["n"] == 3
    assert len(seen_datasets) == 3  # smart_pandas.ask received all three named frames
    assert result.answer.value == "combined analysis"
    assert result.views is not None and len(result.views) == 3


def test_multi_fetch_stage_names_are_per_view_and_distinguishable(monkeypatch, fake_pymrx, tmp_catalog):
    from mrx.smart_pandas import AnswerResult

    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query: router.RoutingDecision(
        mode="multi_fetch", reasoning="r", new_view_queries=["view one", "view two"],
    ))
    # Two genuinely different views (different risk type) — otherwise the
    # second view legitimately reuses the first's just-cataloged fetch,
    # which is correct pipeline behavior but not what this test targets.
    plans = [_plan(url=VALID_URL), _plan(url=VALID_URL.replace("p13=EQDELTACASH", "p13=V_GR_EQVEGA_LT"))]
    calls = {"n": 0}

    def fake_get_link(llm, query, **kw):
        plan = plans[calls["n"]]
        calls["n"] += 1
        return plan

    monkeypatch.setattr(orchestrator.generate_link, "get_link", fake_get_link)
    monkeypatch.setattr(orchestrator.data_fetch, "fetch_data", lambda url: pd.DataFrame({"value": [1]}))
    monkeypatch.setattr(
        orchestrator.smart_pandas, "ask",
        lambda data, question, llm, **kw: AnswerResult(type="string", value="v", narration="n", method="m", code="c"),
    )

    stages = []
    orchestrator.run(FakeChatLLM(["irrelevant"]), "irrelevant", allow_multi_fetch=True, on_stage=stages.append)

    assert stages[0] == "plan:route"
    assert "plan:1" in stages
    assert "plan:2" in stages
    assert "fetch:1" in stages
    assert "fetch:2" in stages
    assert stages[-1] == "answer"


def test_single_view_decision_does_not_set_views_even_with_multi_fetch_allowed(monkeypatch, fake_pymrx, tmp_catalog):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query: router.RoutingDecision(
        mode="single_fetch", reasoning="r", new_view_queries=["the same question"],
    ))
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    result = orchestrator.run(_answer_llm(), "irrelevant", allow_multi_fetch=True)

    assert result.views is None
    assert result.answer.value == 20.0


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
