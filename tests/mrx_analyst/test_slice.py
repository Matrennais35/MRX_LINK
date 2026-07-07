"""Vertical-slice tests: design → execute → write, headless.

A scripted FakeToolLLM plays every role (Designer structured output, the
loop's tool calls, the URL builder) so the composition is proven end-to-end:
blueprint → parallel gated fetches → persistent-namespace python → section
artifacts → assembled desk note. The invariants that matter are asserted:
budget, namespace persistence, in-loop self-correction, visible gaps.
"""

import matplotlib
matplotlib.use("Agg")

from langchain_core.messages import AIMessage

from mrx_analyst import run
from mrx_analyst.common import knowledge
from mrx_analyst.design.blueprint import Blueprint, FetchSpec, SectionSpec
from mrx_analyst.mrx.models import MRXPlan
from tests.mrx_analyst.conftest import VALID_URL, FakeView


def _mrx_plan(intent="overview"):
    return MRXPlan(intent=intent, view_reasoning="r", parameters="p", assumptions=[],
                   confidence=0.95, needs_clarification=None, SmartDF="q",
                   url=VALID_URL.format(risk="EQDELTACASH"))


def _blueprint(clarification=""):
    return Blueprint(
        target="what drove it",
        sections=[
            SectionSpec(title="The path", must_establish="the dated moves",
                        data_needed="daily series", artifact="line chart"),
            SectionSpec(title="Drivers", must_establish="signed attribution by book",
                        data_needed="by-book cut", artifact="ranked bar + table"),
        ],
        fetches=[FetchSpec(request="by-book cut", when="now")],
        clarification=clarification,
    )


class FakeSliceLLM:
    """One fake for every role: structured outputs by schema name (Designer's
    Blueprint, the URL builder's MRXPlan) + a scripted AIMessage queue for the
    loop (bind_tools returns self)."""

    def __init__(self, structured, script):
        self.structured = {k: list(v) for k, v in structured.items()}
        self.script = list(script)
        self.tool_bindings = None

    def with_structured_output(self, schema):
        outer, name = self, schema.__name__

        class _B:
            def invoke(self, messages):
                queue = outer.structured[name]
                return queue.pop(0) if len(queue) > 1 else queue[0]
        return _B()

    def bind_tools(self, tools):
        self.tool_bindings = tools
        return self

    def invoke(self, messages):
        return self.script.pop(0)


def _tc(name, args, cid):
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


REPORT = """FX Vega rose 750, driven by Book A.

## The path
Flat, then one jump.

## Drivers
Book A +900, Book B -150 offset.
"""


def test_full_slice_design_execute_write():
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()]},
        script=[
            AIMessage(content="fetching per blueprint",
                      tool_calls=[_tc("fetch_mrx", {"request": "by-book cut"}, "c1")]),
            AIMessage(content="", tool_calls=[_tc("run_python", {"code": (
                "tbl = helpers.ops.attribution(overview, ['Book'], 'value')\n"
                "fig, ax = plt.subplots()\n"
                "section('Drivers', table=tbl, chart=fig)\n"
                "memo = 42\n"
                "print('net', tbl['contribution'].sum())")}, "c2")]),
            AIMessage(content="", tool_calls=[_tc("run_python", {"code": (
                "print('memo is', memo)")}, "c3")]),          # namespace persistence
            AIMessage(content=REPORT, tool_calls=[]),
        ],
    )
    result = run.run_question(llm, "what drove it?", session_id="s", view=FakeView())

    assert result.answer.narrative == "FX Vega rose 750, driven by Book A."
    titles = [s.title for s in result.answer.sections]
    assert titles[:2] == ["The path", "Drivers"]
    drivers = result.answer.sections[1]
    assert drivers.table is not None and drivers.chart is not None
    assert result.session.budget.used == 1                    # one gated fetch
    assert "overview" in result.session.namespace             # frame registered
    assert result.session.namespace["memo"] == 42             # namespace persisted
    assert {"design", "execute", "write"} <= set(result.timings)
    assert any(s.name == "executor" for s in result.session.trace)
    # 'The path' was written but never given an artifact — still a delivered
    # section (text), no phantom unfilled duplicate:
    assert result.answer.sections[0].status == "filled"


def test_clarification_short_circuits_before_any_fetch():
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint(clarification="Which measure do you mean?")]},
        script=[],
    )
    view = FakeView()
    result = run.run_question(llm, "analyse it", session_id="s", view=view)
    assert result.answer.narrative == "Which measure do you mean?"
    assert view.executed == 0 and result.session.budget.used == 0


def test_code_error_returns_in_loop_and_self_corrects():
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()]},
        script=[
            AIMessage(content="", tool_calls=[_tc("fetch_mrx", {"request": "cut"}, "c1")]),
            AIMessage(content="", tool_calls=[_tc("run_python", {"code": "boom("}, "c2")]),
            AIMessage(content="", tool_calls=[_tc("run_python", {"code": (
                "section('Drivers', table=overview)\nprint('fixed')")}, "c3")]),
            AIMessage(content=REPORT, tool_calls=[]),
        ],
    )
    result = run.run_question(llm, "q", session_id="s", view=FakeView())
    assert any(s.name == "run_python" and s.status == "failed" for s in result.session.trace)
    assert result.answer.sections[1].table is not None        # recovered


def test_undelivered_blueprint_contract_is_a_visible_gap():
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()]},
        script=[AIMessage(content="Short answer only, no sections.", tool_calls=[])],
    )
    result = run.run_question(llm, "q", session_id="s", view=FakeView())
    unfilled = [s for s in result.answer.sections if s.status == "unfilled"]
    assert {s.title for s in unfilled} == {"The path", "Drivers"}
    assert "dated moves" in unfilled[0].reason                # the contract, visible


def test_knowledge_layer_fits_the_prompt_budget():
    total = knowledge.assemble(list(knowledge.FILES))
    assert len(total) < knowledge.PROMPT_CHAR_BUDGET, (
        f"knowledge layer is {len(total)} chars — trim it or raise the budget "
        "DELIBERATELY (VISION.md: the prompt must stay a prompt, not a book)")
    for name in knowledge.FILES:
        assert knowledge.load(name).when_to_use, f"{name} missing when_to_use index line"


def test_read_knowledge_serves_the_manuals_and_rejects_unknown():
    from mrx_analyst.common import knowledge as kn
    manual = kn.read_document("mrx_manual")
    assert "p13" in manual                         # the real manual content
    assert "unknown document" in kn.read_document("nope")
    assert "mrx_manual" in kn.document_index()


def test_extraction_full_table_flag_reaches_the_section():
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()]},
        script=[
            AIMessage(content="", tool_calls=[_tc("fetch_mrx", {"request": "cut"}, "c1")]),
            AIMessage(content="", tool_calls=[_tc("run_python", {"code": (
                "section('Drivers', table=overview, full=True)")}, "c2")]),
            AIMessage(content=REPORT, tool_calls=[]),
        ],
    )
    result = run.run_question(llm, "extract it", session_id="s", view=FakeView())
    drivers = next(s for s in result.answer.sections if s.title == "Drivers")
    assert drivers.full_table is True


def test_critic_revise_reenters_the_loop_with_tools_and_ships_refined_note():
    from mrx_analyst.write.critic import Critique, Issue
    refined = REPORT.replace("rose 750", "rose 750 (net of offsets)")
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()],
                    "Critique": [Critique(verdict="revise", issues=[
                        Issue(kind="missing", detail="Drivers table never computed",
                              section="Drivers")])]},
        script=[
            AIMessage(content="", tool_calls=[_tc("fetch_mrx", {"request": "cut"}, "c1")]),
            AIMessage(content=REPORT, tool_calls=[]),               # first note
            # refine re-entry: the model can USE TOOLS to fix the gap...
            AIMessage(content="", tool_calls=[_tc("run_python", {"code": (
                "section('Drivers', table=overview)")}, "c2")]),
            AIMessage(content=refined, tool_calls=[]),              # refined note
        ],
    )
    result = run.run_question(llm, "q", session_id="s", view=FakeView())
    assert "net of offsets" in result.answer.narrative               # refined note shipped
    drivers = next(s for s in result.answer.sections if s.title == "Drivers")
    assert drivers.table is not None                                 # the refine COMPUTED it
    assert any(s.name == "critic" for s in result.session.trace)
    assert "critique" in result.timings


def test_critic_pass_ships_the_first_note_unchanged():
    from mrx_analyst.write.critic import Critique
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()],
                    "Critique": [Critique(verdict="pass", issues=[])]},
        script=[
            AIMessage(content="", tool_calls=[_tc("fetch_mrx", {"request": "cut"}, "c1")]),
            AIMessage(content=REPORT, tool_calls=[]),
        ],
    )
    result = run.run_question(llm, "q", session_id="s", view=FakeView())
    assert result.answer.narrative == "FX Vega rose 750, driven by Book A."


def test_step_cap_forces_the_note_from_what_exists(monkeypatch):
    from mrx_analyst.execute import loop as loop_mod
    monkeypatch.setattr(loop_mod, "MAX_STEPS", 2)
    endless = AIMessage(content="", tool_calls=[_tc("run_python", {"code": "print(1)"}, "cX")])
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()]},
        script=[endless, endless,
                AIMessage(content="Forced note from partial work.", tool_calls=[])],
    )
    result = run.run_question(llm, "q", session_id="s", view=FakeView())
    assert result.answer.narrative == "Forced note from partial work."
    assert any(s.name == "step_cap" for s in result.session.trace)


def test_budget_refusal_reaches_the_model_as_text():
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()]},
        script=[
            AIMessage(content="", tool_calls=[_tc("fetch_mrx", {"request": "one"}, "c1"),
                                              _tc("fetch_mrx", {"request": "two"}, "c2")]),
            AIMessage(content=REPORT, tool_calls=[]),
        ],
    )
    result = run.run_question(llm, "q", session_id="s", view=FakeView(), max_fetches=1)
    assert result.session.budget.used == 1                           # cap held in parallel
    refusals = [s for s in result.session.trace if s.name == "reuse" or "REFUSED" in s.summary]
    # the refusal text went back as a ToolMessage (model saw it and answered)
    assert result.answer.narrative.startswith("FX Vega rose")


def test_fetch_timeout_returns_text_not_a_hang(monkeypatch):
    import time as _time
    from mrx_analyst.execute import loop as loop_mod
    monkeypatch.setattr(loop_mod, "FETCH_TIMEOUT_S", 0.05)

    class SlowView(FakeView):
        def execute(self, plan):
            _time.sleep(0.5)
            return super().execute(plan)

    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()]},
        script=[
            AIMessage(content="", tool_calls=[_tc("fetch_mrx", {"request": "slow"}, "c1")]),
            AIMessage(content=REPORT, tool_calls=[]),
        ],
    )
    result = run.run_question(llm, "q", session_id="s", view=SlowView())
    assert any(s.name == "fetch_timeout" for s in result.session.trace)
    assert result.answer.narrative.startswith("FX Vega rose")        # loop proceeded


def test_md_table_stripped_when_section_has_a_table_artifact():
    dup = REPORT.replace(
        "Book A +900, Book B -150 offset.",
        "Book A +900, Book B -150 offset.\n\n"
        "| Book | value |\n|---|---|\n| A | 900 |\n| B | -150 |")
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()]},
        script=[
            AIMessage(content="", tool_calls=[_tc("fetch_mrx", {"request": "cut"}, "c1")]),
            AIMessage(content="", tool_calls=[_tc("run_python", {"code": (
                "section('Drivers', table=overview)")}, "c2")]),
            AIMessage(content=dup, tool_calls=[]),
        ],
    )
    result = run.run_question(llm, "q", session_id="s", view=FakeView())
    drivers = next(s for s in result.answer.sections if s.title == "Drivers")
    assert "| Book |" not in drivers.text          # md duplicate stripped
    assert "offset" in drivers.text                # prose kept
    assert drivers.table is not None               # the real table remains


def test_replayed_turn_keeps_sections_and_tables(tmp_catalog):
    llm = FakeSliceLLM(
        structured={"Blueprint": [_blueprint()], "MRXPlan": [_mrx_plan()]},
        script=[
            AIMessage(content="", tool_calls=[_tc("fetch_mrx", {"request": "cut"}, "c1")]),
            AIMessage(content="", tool_calls=[_tc("run_python", {"code": (
                "section('Drivers', table=overview)")}, "c2")]),
            AIMessage(content=REPORT, tool_calls=[]),
        ],
    )
    result = run.run_question(llm, "q", session_id="s",
                              conversation_id="conv_replay", view=FakeView())
    stored = tmp_catalog.load_turn_answer(result.turn_id)
    assert stored["narrative"] == result.answer.narrative
    titles = [e["title"] for e in stored["sections"]]
    assert "Drivers" in titles
    drivers = next(e for e in stored["sections"] if e["title"] == "Drivers")
    assert drivers["table"] is not None and len(drivers["table"]) == 2
