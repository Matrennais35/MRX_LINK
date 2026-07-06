"""Tests for the bounded controller loop (mrx.pipeline.loop).

These assert INVARIANTS (never exceed the fetch cap, every fetch was
validation-gated, the loop always terminates, the count is model-driven) —
not exact fixed fetch counts, since a model-driven loop
makes the count variable by design (see docs/agent_loop_design.md).
"""

import pandas as pd
import pytest

from mrx.pipeline import fetch
from mrx.pipeline import data_fetch
from mrx.pipeline import loop
from mrx.views.multirow import generate_link
from mrx.pipeline.step import StepDecision
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

    def fake_decide(llm, query, gathered, history=(), plan=None):
        seen_gathered.append(list(gathered))
        return seq.pop(0)

    monkeypatch.setattr(loop, "decide_next_step", fake_decide)
    # The loop now also runs a plan_analysis call up front; stub it so loop
    # tests don't need a real LLM for planning (they test the loop, not the
    # plan's content — that's covered in test_step.py).
    monkeypatch.setattr(loop, "plan_analysis", lambda llm, query, **kw: None)
    return seen_gathered


@pytest.fixture
def stub_planning(monkeypatch):
    """Every fetch plans via the real fetch.get_view -> generate_link.get_link;
    stub get_link so it doesn't need a real LLM, but leave validation.validate_plan
    REAL (the URL above is valid) so the gate genuinely runs on every fetch.
    """
    monkeypatch.setattr(generate_link, "get_link", lambda llm, query, **kw: _plan())


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
        StepDecision(action="analyze", reasoning="that's enough"),
    ])

    result = loop.run_agent_loop(_answer_llm(), "what's the average")

    assert len(result.views) == 1
    assert result.answer.value == 20.0
    assert [s.action for s in result.steps] == ["fetch", "analyze"]


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
    monkeypatch.setattr(generate_link, "get_link", lambda llm, query, **kw: bad_plan)
    fake_pymrx["df"] = pd.DataFrame({"value": [1]})
    _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning="go", fetch_query="anything"),
        StepDecision(action="analyze", reasoning="done"),
    ])

    # _plan_and_validate raises PlanValidationError after max_attempts — the
    # gate ran and rejected the URL; no unvalidated fetch happened.
    with pytest.raises(PlanValidationError):
        loop.run_agent_loop(_answer_llm(), "q", max_attempts=1)


def test_analyze_with_no_data_raises_a_clean_error(monkeypatch, fake_pymrx, stub_planning):
    # If the model chooses to ANALYZE (compute over data) on step 1 with
    # nothing fetched, there's nothing to compute over — must be a caught
    # PipelineError, not a crash. (respond with no data is fine — see below.)
    _script_decisions(monkeypatch, [
        StepDecision(action="analyze", reasoning="I'll just compute"),
    ])

    with pytest.raises(AnswerError):
        loop.run_agent_loop(_answer_llm(), "q")


def test_on_step_fires_with_each_decisions_live_content(monkeypatch, fake_pymrx, stub_planning, stub_answer):
    # The live-thinking callback: on_step must fire once per decision, carrying
    # the actual StepDecision (action + reasoning + fetch_query) so the UI can
    # show real progress, not an opaque label.
    fake_pymrx["df"] = pd.DataFrame({"value": [1, 2]})
    _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning="need by-desk data", fetch_query="FX Vega by desk"),
        StepDecision(action="analyze", reasoning="enough to answer"),
    ])

    seen = []
    loop.run_agent_loop(_answer_llm(), "q", on_step=lambda n, d: seen.append((n, d.action, d.reasoning)))

    assert seen == [
        (1, "fetch", "need by-desk data"),
        (2, "analyze", "enough to answer"),
    ]


def test_respond_answers_directly_with_no_data_and_no_error(monkeypatch, fake_pymrx, stub_planning):
    # The headline new behavior: a question that doesn't need data (e.g.
    # "summarise the conversation") is answered directly in prose, with NO
    # fetch and NO error — even though nothing was gathered.
    _script_decisions(monkeypatch, [
        StepDecision(action="respond", reasoning="this is a conversation summary, no data needed"),
    ])
    # respond calls smart_pandas.respond -> llm.invoke; give it a plain LLM.
    from tests.conftest import FakeChatLLM
    prose_llm = FakeChatLLM(["Here is a summary of what we discussed."])

    result = loop.run_agent_loop(prose_llm, "summarise the conversation")

    assert result.answer.type == "string"
    assert result.answer.narration == "Here is a summary of what we discussed."
    assert result.answer.code == ""  # no code was run
    assert len(result.views) == 0    # no data fetched
    assert [s.action for s in result.steps] == ["respond"]


def test_each_decision_sees_the_data_gathered_so_far(monkeypatch, fake_pymrx, stub_planning, stub_answer):
    fake_pymrx["df"] = pd.DataFrame({"value": [10, 20, 30]})
    seen = _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning="first", fetch_query="a"),
        StepDecision(action="fetch", reasoning="second", fetch_query="b"),
        StepDecision(action="analyze", reasoning="enough"),
    ])

    loop.run_agent_loop(_answer_llm(), "q", max_fetches=5)

    # Step 1 saw nothing; step 2 saw the first view; step 3 saw both.
    assert seen[0] == []
    assert len(seen[1]) == 1
    assert len(seen[2]) == 2


def _seed_conversation_dataset(catalog, conversation_id, df, *, description="FX Vega by desk"):
    """Save a dataset into the catalog under a conversation, as if a prior
    turn had fetched it — so a follow-up loop run can seed from it.
    """
    dataset = catalog.Dataset(
        id=catalog.new_dataset_id(), session_id="s", conversation_id=conversation_id,
        query="original question", plan=_plan(), created_at="2026-06-01T00:00:00+00:00",
        description=description,
    )
    catalog.save(dataset, df)
    return dataset


def test_followup_answers_from_prior_turn_data_with_no_fresh_fetch(monkeypatch, fake_pymrx, stub_planning, stub_answer, tmp_catalog):
    # The reported bug: "plot the variation" as a follow-up should answer from
    # already-fetched conversation data, NOT build a new MRX plan.
    df = pd.DataFrame({"date": ["2026-06-01", "2026-06-02"], "fx_vega": [900, 950]})
    _seed_conversation_dataset(tmp_catalog, "conv_followup", df)

    # Model chooses "answer" immediately — it can, because the seeded context
    # is present on step 1.
    _script_decisions(monkeypatch, [
        StepDecision(action="analyze", reasoning="the by-desk data is already here, just plot it"),
    ])
    # If a fetch were attempted, this would fire.
    monkeypatch.setattr(
        data_fetch, "fetch_data",
        lambda url: (_ for _ in ()).throw(AssertionError("no fresh fetch should happen")),
    )

    result = loop.run_agent_loop(_answer_llm(), "plot the variation", conversation_id="conv_followup")

    assert result.answer is not None
    # No fresh fetch step ran; the answer came from seeded context.
    assert not [s for s in result.steps if s.action == "fetch" and not s.capped]


def test_first_decision_sees_the_seeded_prior_turn_context(monkeypatch, fake_pymrx, stub_planning, stub_answer, tmp_catalog):
    df = pd.DataFrame({"fx_vega": [900]})
    _seed_conversation_dataset(tmp_catalog, "conv_seed", df, description="FX Vega by desk")
    seen = _script_decisions(monkeypatch, [
        StepDecision(action="analyze", reasoning="present"),
    ])

    loop.run_agent_loop(_answer_llm(), "plot it", conversation_id="conv_seed")

    # Step 1's gathered-so-far already contains the prior turn's data.
    assert len(seen[0]) == 1
    assert "earlier question" in seen[0][0][0]  # the seeded-context label


def test_seeded_context_does_not_consume_the_fetch_cap(monkeypatch, fake_pymrx, stub_planning, stub_answer, tmp_catalog):
    # A follow-up that DOES need new data should still get its full fetch
    # budget — seeded context must not count against max_fetches.
    df = pd.DataFrame({"fx_vega": [900]})
    _seed_conversation_dataset(tmp_catalog, "conv_cap", df)
    fake_pymrx["df"] = pd.DataFrame({"value": [1, 2]})
    _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning="need new cut 1", fetch_query="a"),
        StepDecision(action="fetch", reasoning="need new cut 2", fetch_query="b"),
        StepDecision(action="analyze", reasoning="done"),
    ])

    result = loop.run_agent_loop(_answer_llm(), "compare with something new", conversation_id="conv_cap", max_fetches=2)

    fresh = [s for s in result.steps if s.action == "fetch" and not s.capped]
    assert len(fresh) == 2  # both fresh fetches allowed despite 1 seeded context view


def test_step_reasoning_is_threaded_into_the_gathered_frame_label(monkeypatch, fake_pymrx, stub_planning, stub_answer):
    # The provenance fix: a gathered frame's label must include WHY it was
    # fetched, so a later decision (and the answer stage) can relate frames.
    fake_pymrx["df"] = pd.DataFrame({"value": [1, 2]})
    seen = _script_decisions(monkeypatch, [
        StepDecision(action="fetch", reasoning="DESK_A dominates so drill in", fetch_query="DESK_A by deal"),
        StepDecision(action="fetch", reasoning="second", fetch_query="b"),
        StepDecision(action="analyze", reasoning="done"),
    ])

    loop.run_agent_loop(_answer_llm(), "q", max_fetches=5)

    # By step 2, the first frame's label carries its fetch reasoning.
    first_label = seen[1][0][0]
    assert "fetched because" in first_label
    assert "DESK_A dominates" in first_label
