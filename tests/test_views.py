"""Proves the View interface is a real seam, not cosmetic: a second, entirely
fake View (no MRX, no URL) runs end-to-end through the loop with ZERO edits to
fetch / router / loop / catalog. This is the whole point of the refactor — a
new view is "write a View + pass it".
"""

import pandas as pd
import pytest

from mrx.pipeline import loop
from mrx.pipeline.models import MRXPlan
from mrx.pipeline.step import StepDecision
from mrx.views.base import View
from tests.conftest import FakeChatLLM


class FakeView:
    """A second view that has nothing to do with MRX — it fabricates a tiny
    dataframe instead of hitting any backend. If the loop can run this, the
    core genuinely doesn't know or care which view it's running.
    """

    name = "fake"
    description = "A fake view for testing the seam — returns canned data."

    def __init__(self):
        self.planned = 0
        self.executed = 0

    def plan(self, llm, query, *, prior_attempts=()):
        self.planned += 1
        # A minimal valid MRXPlan — the catalog stores it, but nothing in the
        # fake path parses its URL (this view's fingerprint ignores it).
        return MRXPlan(
            intent=f"fake view for: {query}", view_reasoning="r", parameters="p",
            assumptions=[], confidence=0.99, needs_clarification=None,
            SmartDF=query, url="fake://no-real-url",
        )

    def validate(self, plan, *, min_confidence=0.7):
        return None  # the fake plan is always valid

    def execute(self, plan):
        self.executed += 1
        return pd.DataFrame({"value": [100, 200, 300]})

    def fingerprint(self, plan):
        # This view's reuse key is just its intent — no URL parsing at all,
        # proving the reuse gate no longer assumes MRX URLs.
        return {"intent": plan.intent}


def test_fake_view_satisfies_the_view_protocol():
    assert isinstance(FakeView(), View)


def _answer_llm():
    return FakeChatLLM([
        '```python\nresult = {"type": "number", "value": df["value"].mean()}\n```',
        "The average is 200.",
    ])


def test_loop_runs_end_to_end_against_a_non_mrx_view(monkeypatch):
    # The seam proof: pass a FakeView to the loop; it plans, executes, and
    # answers through it — no generate_link, no validation, no data_fetch,
    # no URL parsing anywhere. Zero core code changed to make this work.
    view = FakeView()

    monkeypatch.setattr(loop, "decide_next_step", _script([
        StepDecision(action="fetch", reasoning="get the fake data", fetch_query="anything"),
        StepDecision(action="analyze", reasoning="that's enough"),
    ]))

    result = loop.run_agent_loop(_answer_llm(), "what's the average", view=view)

    assert view.planned == 1
    assert view.executed == 1
    assert result.answer.value == 200.0
    assert len(result.views) == 1


def _script(decisions):
    seq = list(decisions)

    def fake_decide(llm, query, gathered, history=()):
        return seq.pop(0)

    return fake_decide
