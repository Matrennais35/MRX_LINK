"""Headless invariant tests for run_turn — the safety case for the rebuild:
budget capped in code, every fetch gated, respond short-circuits, reuse costs
nothing, exactly one refine, wave-2 drill sees wave-1 profiles, all traced.
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

from mrx_analyst.agents.analyst import AnalysisSpec, ToolkitCall
from mrx_analyst.agents.critic import Critique, Issue
from mrx_analyst.agents.datascout import FetchSpec, MultiFetchPlan
from mrx_analyst.agents.planner import AnalysisPlan
from mrx_analyst.core import orchestrator
from mrx_analyst.core.models import MRXPlan
from mrx_analyst.storage import catalog

VALID_URL = (
    "https://market.risk.echonet/Market%20Risk%20Explorer/Market%20Risk%20Explorer.application"
    "?env=Production&viewid=6168&p1=EQDUSNLH&p1021=Current&p1029=Total"
    "&p1217=RowGrpRiskType&p27=2026-06-30&p28=2026-06-01&p13={risk}"
)


def _mrx_plan(risk="EQDELTACASH", intent="fx vega by book"):
    return MRXPlan(intent=intent, view_reasoning="r", parameters="p", assumptions=[],
                   confidence=0.95, needs_clarification=None, SmartDF="q",
                   url=VALID_URL.format(risk=risk))


def _plan(needs_data=True, goals=("overview",)):
    return AnalysisPlan(target="the driver", approach="overview then drill",
                        representation="ranked bar", success_criteria="names the driver",
                        needs_data=needs_data, fetch_goals=list(goals))


def _fetch_plan(n=1, drill=False):
    return MultiFetchPlan(
        specs=[FetchSpec(role="overview", justification=f"goal {i}",
                         mrx_plan=_mrx_plan(risk=f"RISK{i}", intent=f"view {i}"))
               for i in range(n)],
        drill_after_overview=drill, reasoning="r",
    )


def _spec(ops=None, fallback=None):
    return AnalysisSpec(reasoning="r", ops=ops or [], fallback_code_request=fallback)


def _attribution_spec(dataset):
    import json
    return _spec(ops=[ToolkitCall(tool="attribution",
                                  args_json=json.dumps({"dataset": dataset, "group_cols": ["Book"]}))])


class _Msg:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """Queue-per-schema structured outputs + a text queue for narrator calls."""

    def __init__(self, structured=None, texts=None):
        self.structured = {k: list(v) for k, v in (structured or {}).items()}
        self.texts = list(texts or ["The narrative."])
        self.structured_calls = []

    def with_structured_output(self, schema):
        outer = self

        class _Bound:
            def invoke(self, messages):
                name = schema.__name__
                outer.structured_calls.append((name, messages))
                queue = outer.structured.get(name)
                if not queue:
                    raise AssertionError(f"unexpected structured call for {name}")
                return queue.pop(0) if len(queue) > 1 else queue[0]
        return _Bound()

    def invoke(self, messages):
        return _Msg(self.texts.pop(0) if len(self.texts) > 1 else self.texts[0])


class FakeView:
    name = "fake"

    def __init__(self):
        self.executed = 0

    def validate(self, plan, **kw):
        pass

    def execute(self, plan):
        self.executed += 1
        return pd.DataFrame({"Book": ["A", "B"], "value": [900.0, -150.0]})

    def fingerprint(self, plan):
        from urllib.parse import parse_qsl, urlparse
        return dict(parse_qsl(urlparse(plan.url).query))


def _passing_critique():
    return Critique(verdict="pass", issues=[])


def test_respond_short_circuit_makes_exactly_two_llm_calls():
    llm = FakeLLM(structured={"AnalysisPlan": [_plan(needs_data=False)]},
                  texts=["A direct prose answer."])
    result = orchestrator.run_turn(llm, "summarise", session_id="s")
    assert result.answer.narrative == "A direct prose answer."
    assert result.answer.table is None and result.answer.chart is None
    assert [n for n, _ in llm.structured_calls] == ["AnalysisPlan"]  # + 1 text call = 2 total


def test_full_data_turn_produces_answer_with_facts_table():
    view = FakeView()
    llm = FakeLLM(structured={
        "AnalysisPlan": [_plan()],
        "MultiFetchPlan": [_fetch_plan(n=1)],
        "AnalysisSpec": [_attribution_spec("view_0")],
        "Critique": [_passing_critique()],
    })
    result = orchestrator.run_turn(llm, "what drove it", session_id="s", view=view)
    assert view.executed == 1
    assert result.answer.table is not None
    assert list(result.answer.table["contribution"]) == [900.0, -150.0]
    assert result.answer.narrative == "The narrative."
    # trace covers agents + gates
    kinds = {(s.kind, s.name) for s in result.ctx.trace}
    assert ("agent", "planner") in kinds and ("agent", "datascout") in kinds
    assert ("gate", "fetch") in kinds and ("agent", "critic") in kinds


def test_budget_cap_is_enforced_across_a_wave(monkeypatch):
    # This test is about the BUDGET under parallelism — which 2 of the 3 specs
    # win the race is nondeterministic by design, so the analyze stage (which
    # would need to reference a specific surviving label) is stubbed out.
    from mrx_analyst.agents.analyst import Facts
    monkeypatch.setattr(orchestrator, "_compute_facts",
                        lambda llm, ctx: Facts(metrics={"ok": 1}))
    view = FakeView()
    llm = FakeLLM(structured={
        "AnalysisPlan": [_plan()],
        "MultiFetchPlan": [_fetch_plan(n=3)],           # wants 3 fetches
        "Critique": [_passing_critique()],
    })
    result = orchestrator.run_turn(llm, "q", session_id="s", view=view, max_fetches=2)
    assert view.executed == 2                            # cap held under parallelism
    assert result.ctx.budget.used == 2
    assert any(s.name == "budget" and s.status == "refused" for s in result.ctx.trace)


def test_reuse_costs_zero_budget_on_a_follow_up():
    view = FakeView()

    def llm_for():
        # Both turns design the SAME view (matching params) and analyze the
        # evidence labelled "overview" (the label derives from plan.intent).
        return FakeLLM(structured={
            "AnalysisPlan": [_plan()],
            "MultiFetchPlan": [MultiFetchPlan(specs=[FetchSpec(
                role="overview", justification="g", mrx_plan=_mrx_plan(intent="overview"))],
                drill_after_overview=False, reasoning="r")],
            "AnalysisSpec": [AnalysisSpec(reasoning="r", ops=[ToolkitCall(
                tool="attribution",
                args_json='{"dataset": "overview", "group_cols": ["Book"]}')])],
            "Critique": [_passing_critique()],
        })

    r1 = orchestrator.run_turn(llm_for(), "q1", session_id="s", conversation_id="conv_x", view=view)
    r2 = orchestrator.run_turn(llm_for(), "q2", session_id="s", conversation_id="conv_x", view=view)
    assert view.executed == 1                            # second turn reused, no new MRX call
    assert r2.ctx.budget.used == 0


def test_wave2_drill_sees_wave1_profiles():
    view = FakeView()
    llm = FakeLLM(structured={
        "AnalysisPlan": [_plan()],
        "MultiFetchPlan": [_fetch_plan(n=1, drill=True),                       # wave 1
                           _fetch_plan(n=1)],                                   # wave 2 (drill)
        "AnalysisSpec": [_attribution_spec("view_0")],
        "Critique": [_passing_critique()],
    })
    orchestrator.run_turn(llm, "q", session_id="s", view=view)
    # The SECOND MultiFetchPlan call's prompt must contain the wave-1 profile.
    scout_calls = [m for n, m in llm.structured_calls if n == "MultiFetchPlan"]
    assert len(scout_calls) == 2
    wave2_prompt = scout_calls[1][-1].content
    assert "PROFILES OF DATA FETCHED SO FAR" in wave2_prompt
    assert "net sum" in wave2_prompt                     # the profile's content


def test_critic_revise_triggers_exactly_one_refine_then_ships():
    view = FakeView()
    llm = FakeLLM(
        structured={
            "AnalysisPlan": [_plan()],
            "MultiFetchPlan": [_fetch_plan(n=1)],
            "AnalysisSpec": [_attribution_spec("view_0")],
            # ALWAYS revise — the cap in code must ship after one refine anyway.
            "Critique": [Critique(verdict="revise",
                                  issues=[Issue(kind="narrative", detail="missing the driver")])],
        },
        texts=["first narrative", "revised narrative"],
    )
    result = orchestrator.run_turn(llm, "q", session_id="s", view=view)
    assert result.answer.narrative == "revised narrative"
    critic_calls = [n for n, _ in llm.structured_calls if n == "Critique"]
    assert len(critic_calls) == 1                        # one critique, one refine, ship


def test_failed_analyst_op_falls_back_to_codegen():
    view = FakeView()
    bad = AnalysisSpec(reasoning="r", ops=[ToolkitCall(
        tool="attribution", args_json='{"dataset": "nope", "group_cols": ["Book"]}')])
    llm = FakeLLM(
        structured={
            "AnalysisPlan": [_plan()],
            "MultiFetchPlan": [_fetch_plan(n=1)],
            "AnalysisSpec": [bad, bad],                  # wrong twice -> codegen
            "Critique": [_passing_critique()],
        },
        texts=['```python\nresult = {"type": "number", "value": float(view_0["value"].sum())}\n```',
               "the narrative"],
    )
    result = orchestrator.run_turn(llm, "q", session_id="s", view=view)
    assert result.answer.value == "750.0"                # codegen computed 900-150
    assert any(s.name == "codegen" for s in result.ctx.trace)


def test_turn_and_trace_are_persisted():
    view = FakeView()
    llm = FakeLLM(structured={
        "AnalysisPlan": [_plan()],
        "MultiFetchPlan": [_fetch_plan(n=1)],
        "AnalysisSpec": [_attribution_spec("view_0")],
        "Critique": [_passing_critique()],
    })
    result = orchestrator.run_turn(llm, "q", session_id="s", conversation_id="conv_p", view=view)
    turns = catalog.list_turns(conversation_id="conv_p")
    assert len(turns) == 1 and turns[0].id == result.turn_id
    steps = catalog.list_steps(turn_id=result.turn_id)
    assert len(steps) == len(result.ctx.trace) > 0
    assert steps[0].step_num == 1
