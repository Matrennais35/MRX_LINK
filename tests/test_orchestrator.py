import time

import pandas as pd
import pytest

from mrx.pipeline import catalog, orchestrator, router
from mrx.pipeline.models import MRXPlan
from mrx.pipeline.pipeline_errors import AnswerError, PlanGenerationError, PlanValidationError
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


def test_answer_from_context_skips_planning_and_fetching_entirely(monkeypatch, fake_pymrx, tmp_catalog):
    # The regression this covers: a follow-up like "what was the biggest
    # daily variation" over data already fetched must NOT re-plan or
    # re-fetch — router.route() being offered "answer_from_context" and
    # choosing it should short-circuit straight to the answer stage.
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    get_link_calls = {"n": 0}
    real_get_link = orchestrator.generate_link.get_link

    def counting_get_link(llm, query, **kw):
        get_link_calls["n"] += 1
        return real_get_link(llm, query, **kw)

    monkeypatch.setattr(orchestrator.generate_link, "get_link", counting_get_link)

    fetch_calls = {"n": 0}
    real_fetch = orchestrator.data_fetch.fetch_data

    def counting_fetch(url):
        fetch_calls["n"] += 1
        return real_fetch(url)

    monkeypatch.setattr(orchestrator.data_fetch, "fetch_data", counting_fetch)

    ask_calls = []
    real_ask = orchestrator.smart_pandas.ask

    def spy_ask(data, question, llm, **kw):
        ask_calls.append(question)
        return real_ask(data, question, llm, **kw)

    monkeypatch.setattr(orchestrator.smart_pandas, "ask", spy_ask)

    # First turn: a normal fetch, single_fetch mode (no context yet).
    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="single_fetch", reasoning="first question, nothing to reuse", new_view_queries=[query],
    ))
    first = orchestrator.run(
        _answer_llm(), "what is the average value",
        session_id="sess1", conversation_id="conv1", allow_multi_fetch=True,
    )
    assert get_link_calls["n"] == 1
    assert fetch_calls["n"] == 1

    # Second turn: router now sees context and chooses answer_from_context.
    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="answer_from_context", reasoning="pure analysis of existing data", new_view_queries=[],
    ))
    second = orchestrator.run(
        _answer_llm(), "what was the biggest daily variation",
        session_id="sess1", conversation_id="conv1", allow_multi_fetch=True,
    )

    assert get_link_calls["n"] == 1  # unchanged — no new plan for the follow-up
    assert fetch_calls["n"] == 1  # unchanged — no new MRX fetch for the follow-up
    assert second.reused_dataset_id is not None  # answered from the catalog, not a fresh fetch
    assert second.df.equals(first.df)
    # The actual follow-up text must reach smart_pandas.ask — NOT the
    # first turn's stored plan.SmartDF ("What is the average value?"),
    # which would silently re-answer the old question instead of this one.
    assert ask_calls[-1] == "what was the biggest daily variation"


def test_answer_from_context_is_never_offered_without_a_conversation_id(monkeypatch, fake_pymrx, tmp_catalog):
    # allow_multi_fetch=True but no conversation_id: router.route() must be
    # called with an empty context_datasets, same as a brand-new
    # conversation — answer_from_context has nothing to look up against.
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())

    seen_context = {}

    def spy_route(llm, query, **kw):
        seen_context["context_datasets"] = kw.get("context_datasets")
        return router.RoutingDecision(mode="single_fetch", reasoning="r", new_view_queries=[query])

    monkeypatch.setattr(orchestrator.router, "route", spy_route)

    orchestrator.run(_answer_llm(), "what is the average value", session_id="sess1", allow_multi_fetch=True)

    assert seen_context["context_datasets"] == []


def test_answer_from_context_is_scoped_to_its_own_conversation(monkeypatch, fake_pymrx, tmp_catalog):
    # Data fetched under a different conversation_id must not leak into
    # this conversation's answer-from-context lookup.
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())
    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="single_fetch", reasoning="r", new_view_queries=[query],
    ))

    orchestrator.run(
        _answer_llm(), "what is the average value",
        session_id="sess1", conversation_id="conv_other", allow_multi_fetch=True,
    )

    seen_context = {}

    def spy_route(llm, query, **kw):
        seen_context["context_datasets"] = kw.get("context_datasets")
        return router.RoutingDecision(mode="single_fetch", reasoning="r", new_view_queries=[query])

    monkeypatch.setattr(orchestrator.router, "route", spy_route)

    orchestrator.run(
        _answer_llm(), "a totally different first question",
        session_id="sess1", conversation_id="conv_mine", allow_multi_fetch=True,
    )

    assert seen_context["context_datasets"] == []


def test_answer_from_context_survives_a_fresh_run_call_with_the_same_conversation_id(monkeypatch, fake_pymrx, tmp_catalog):
    # Simulates "the browser refreshed" — session_id changes (a fresh
    # Streamlit session), but conversation_id (kept in the URL) doesn't.
    # answer_from_context must still find the conversation's data by
    # conversation_id, not session_id, since session_id is now different.
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())
    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="single_fetch", reasoning="r", new_view_queries=[query],
    ))

    first = orchestrator.run(
        _answer_llm(), "what is the average value",
        session_id="sess1", conversation_id="conv1", allow_multi_fetch=True,
    )

    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="answer_from_context", reasoning="pure analysis of existing data", new_view_queries=[],
    ))
    # Different session_id (as if the page was refreshed), same conversation_id.
    second = orchestrator.run(
        _answer_llm(), "what was the biggest daily variation",
        session_id="sess2_after_refresh", conversation_id="conv1", allow_multi_fetch=True,
    )

    assert second.df.equals(first.df)


def test_answer_from_context_raises_a_clean_error_when_stored_data_cannot_be_loaded(monkeypatch, fake_pymrx, tmp_catalog):
    # If every context dataset's parquet file is missing/corrupt (catalog
    # metadata present, data gone — e.g. a partial wipe of .mrx_catalog/),
    # this must surface as a caught PipelineError (AnswerError), not an
    # uncaught IndexError from `views[0]` on an empty list — app.py only
    # catches PipelineError, so anything else reaches the user as a raw
    # traceback instead of a clean message.
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan())
    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="single_fetch", reasoning="r", new_view_queries=[query],
    ))

    orchestrator.run(
        _answer_llm(), "what is the average value",
        session_id="sess1", conversation_id="conv1", allow_multi_fetch=True,
    )

    # Simulate the stored dataframe's parquet file being gone.
    monkeypatch.setattr(orchestrator, "_load_reused_df", lambda dataset_id: None)
    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="answer_from_context", reasoning="pure analysis of existing data", new_view_queries=[],
    ))

    with pytest.raises(AnswerError):
        orchestrator.run(
            _answer_llm(), "what was the biggest daily variation",
            session_id="sess1", conversation_id="conv1", allow_multi_fetch=True,
        )


def test_multi_fetch_runs_one_get_link_and_fetch_per_view(monkeypatch, fake_pymrx, tmp_catalog):
    # NOTE: views now fetch concurrently (see orchestrator.run), so these
    # fakes are keyed by the view query TEXT (deterministic regardless of
    # thread scheduling) rather than a shared call-order counter, and use a
    # real Lock around the shared call-count state to avoid a genuine data
    # race under concurrent access.
    import threading
    view_urls_by_query = {
        "by desk": VALID_URL,
        "by product": VALID_URL.replace("p1=EQDUSNLH", "p1=EQDUSNDX") + "&p1218=RowGrpPrdInlNo",
        "by deal": VALID_URL.replace("p13=EQDELTACASH", "p13=V_GR_EQVEGA_LT"),
    }
    dfs_by_query = {
        "by desk": pd.DataFrame({"value": [1, 2]}),
        "by product": pd.DataFrame({"value": [3, 4]}),
        "by deal": pd.DataFrame({"value": [5, 6]}),
    }

    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="multi_fetch", reasoning="needs three views",
        new_view_queries=["by desk", "by product", "by deal"],
    ))

    lock = threading.Lock()
    get_link_calls = {"n": 0}
    fetch_calls = {"n": 0}

    def fake_get_link(llm, query, **kw):
        with lock:
            get_link_calls["n"] += 1
        return _plan(url=view_urls_by_query[query], intent=f"view: {query}")

    monkeypatch.setattr(orchestrator.generate_link, "get_link", fake_get_link)

    def fake_fetch(url):
        query = next(q for q, u in view_urls_by_query.items() if u == url)
        with lock:
            fetch_calls["n"] += 1
        return dfs_by_query[query]

    monkeypatch.setattr(orchestrator.data_fetch, "fetch_data", fake_fetch)

    seen_datasets = {}

    def fake_ask(data, question, llm, **kw):
        with lock:
            seen_datasets.update(data if isinstance(data, dict) else {"df": data})
        from mrx.pipeline.smart_pandas import AnswerResult
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


def test_multi_fetch_with_identical_view_intents_loses_no_dataframe(monkeypatch, fake_pymrx, tmp_catalog):
    # Regression test: if the LLM writes the same one-sentence `intent` for
    # two different views, a naive {intent: df} dict would silently drop
    # one dataframe via key-overwrite before smart_pandas.ask ever sees it.
    # Fakes are keyed by view query text (deterministic under the
    # concurrent execution orchestrator.run now uses for multi-fetch), with
    # a Lock around shared call-count state.
    import threading
    view_urls_by_query = {
        "by desk": VALID_URL,
        "by product": VALID_URL.replace("p1=EQDUSNLH", "p1=EQDUSNDX") + "&p1218=RowGrpPrdInlNo",
        "by deal": VALID_URL.replace("p13=EQDELTACASH", "p13=V_GR_EQVEGA_LT"),
    }
    dfs_by_query = {"by desk": pd.DataFrame({"value": [1]}), "by product": pd.DataFrame({"value": [2]}), "by deal": pd.DataFrame({"value": [3]})}

    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="multi_fetch", reasoning="needs three views",
        new_view_queries=["by desk", "by product", "by deal"],
    ))

    lock = threading.Lock()
    get_link_calls = {"n": 0}
    fetch_calls = {"n": 0}

    def fake_get_link(llm, query, **kw):
        with lock:
            get_link_calls["n"] += 1
        # All three views share the identical intent — the actual regression trigger.
        return _plan(url=view_urls_by_query[query], intent="FX Vega breakdown")

    monkeypatch.setattr(orchestrator.generate_link, "get_link", fake_get_link)

    def fake_fetch(url):
        query = next(q for q, u in view_urls_by_query.items() if u == url)
        with lock:
            fetch_calls["n"] += 1
        return dfs_by_query[query]

    monkeypatch.setattr(orchestrator.data_fetch, "fetch_data", fake_fetch)

    seen_datasets = {}

    def fake_ask(data, question, llm, **kw):
        with lock:
            seen_datasets.update(data if isinstance(data, dict) else {"df": data})
        from mrx.pipeline.smart_pandas import AnswerResult
        return AnswerResult(type="string", value="ok", narration="n", method="m", code="c")

    monkeypatch.setattr(orchestrator.smart_pandas, "ask", fake_ask)

    orchestrator.run(
        FakeChatLLM(["irrelevant"]), "analyse the FX Vega breakdown",
        allow_multi_fetch=True,
    )

    assert len(seen_datasets) == 3  # all three views survived, none dropped
    values = sorted(df["value"].iloc[0] for df in seen_datasets.values())
    assert values == [1, 2, 3]


def test_multi_fetch_views_run_concurrently_not_sequentially(monkeypatch, fake_pymrx, tmp_catalog):
    # Regression test for the efficiency fix: 3 independent views used to
    # run one after another, paying ~3x the latency for no reason. Give
    # each view a fake fetch that sleeps, and assert the total wall-clock
    # time is close to ONE sleep, not three summed — proving they actually
    # overlap in time rather than merely producing correct results.
    from mrx.pipeline.smart_pandas import AnswerResult

    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="multi_fetch", reasoning="r", new_view_queries=["view one", "view two", "view three"],
    ))
    urls_by_query = {
        "view one": VALID_URL,
        "view two": VALID_URL.replace("p1=EQDUSNLH", "p1=EQDUSNDX") + "&p1218=RowGrpPrdInlNo",
        "view three": VALID_URL.replace("p13=EQDELTACASH", "p13=V_GR_EQVEGA_LT"),
    }
    monkeypatch.setattr(orchestrator.generate_link, "get_link", lambda llm, query, **kw: _plan(url=urls_by_query[query]))

    SLEEP_SECONDS = 0.15

    def slow_fetch(url):
        time.sleep(SLEEP_SECONDS)
        return pd.DataFrame({"value": [1]})

    monkeypatch.setattr(orchestrator.data_fetch, "fetch_data", slow_fetch)
    monkeypatch.setattr(
        orchestrator.smart_pandas, "ask",
        lambda data, question, llm, **kw: AnswerResult(type="string", value="v", narration="n", method="m", code="c"),
    )

    start = time.perf_counter()
    orchestrator.run(FakeChatLLM(["irrelevant"]), "irrelevant", allow_multi_fetch=True)
    elapsed = time.perf_counter() - start

    # Sequential would take ~3 * SLEEP_SECONDS; concurrent should take ~1x.
    # Generous margin for CI/thread-scheduling overhead.
    assert elapsed < SLEEP_SECONDS * 2, (
        f"expected concurrent fetches to take ~{SLEEP_SECONDS}s, took {elapsed:.2f}s "
        f"(looks sequential, ~{SLEEP_SECONDS * 3:.2f}s expected if so)"
    )


def test_multi_fetch_stage_names_are_per_view_and_distinguishable(monkeypatch, fake_pymrx, tmp_catalog):
    from mrx.pipeline.smart_pandas import AnswerResult

    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
        mode="multi_fetch", reasoning="r", new_view_queries=["view one", "view two"],
    ))
    # Two genuinely different views (different risk type) — otherwise the
    # second view legitimately reuses the first's just-cataloged fetch,
    # which is correct pipeline behavior but not what this test targets.
    # Keyed by view query text (deterministic under concurrent execution),
    # not a shared call-order counter.
    plans_by_query = {
        "view one": _plan(url=VALID_URL),
        "view two": _plan(url=VALID_URL.replace("p13=EQDELTACASH", "p13=V_GR_EQVEGA_LT")),
    }

    def fake_get_link(llm, query, **kw):
        return plans_by_query[query]

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
    monkeypatch.setattr(orchestrator.router, "route", lambda llm, query, **kw: router.RoutingDecision(
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
        raise FileNotFoundError("manual.md missing")

    monkeypatch.setattr(orchestrator.generate_link, "get_link", broken_get_link)

    with pytest.raises(PlanGenerationError):
        orchestrator.run(object(), "irrelevant", max_attempts=1)
