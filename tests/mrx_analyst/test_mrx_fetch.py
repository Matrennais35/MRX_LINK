"""Tests for the validated fetch step — the invariants that make it safe:
reuse costs zero budget, the gate always runs, the cap is enforced in code."""

import pandas as pd
import pytest

from mrx_analyst.core.context import FetchBudget, RunContext
from mrx_analyst.core.errors import BudgetExhausted, PlanValidationError
from mrx_analyst.mrx.models import MRXPlan
from mrx_analyst.storage import catalog
from mrx_analyst.tools import mrx_fetch

VALID_URL = (
    "https://market.risk.echonet/Market%20Risk%20Explorer/Market%20Risk%20Explorer.application"
    "?env=Production&viewid=6168&p1=EQDUSNLH&p1021=Current&p1029=Total"
    "&p1217=RowGrpRiskType&p27=2026-06-30&p28=2026-06-01&p13=EQDELTACASH"
)


def _plan(url=VALID_URL, intent="fx vega by book"):
    return MRXPlan(intent=intent, view_reasoning="r", parameters="p", assumptions=[],
                   confidence=0.95, needs_clarification=None, SmartDF="q", url=url)


class FakeView:
    """A view that counts validations/executions and can be told to reject."""

    name = "fake"

    def __init__(self, reject=False):
        self.reject = reject
        self.validated = 0
        self.executed = 0

    def validate(self, plan, **kw):
        self.validated += 1
        if self.reject:
            raise PlanValidationError("rejected by gate")

    def execute(self, plan):
        self.executed += 1
        return pd.DataFrame({"Book": ["A", "B"], "value": [10.0, -3.0]})

    def fingerprint(self, plan):
        # param-dict fingerprint (like parse_mrx_url) so the reuse gate works
        from urllib.parse import parse_qsl, urlparse
        return dict(parse_qsl(urlparse(plan.url).query))


def _ctx(**kw):
    return RunContext(query="q", session_id="s", conversation_id="conv_t", **kw)


def test_fetch_validates_executes_profiles_and_catalogs():
    ctx, view = _ctx(), FakeView()
    ev = mrx_fetch.fetch_evidence(_plan(), view, ctx, query="q")
    assert view.validated == 1 and view.executed == 1
    assert ev.provenance == "fetched"
    assert ev.profile.value_columns == ["value"]
    assert ctx.budget.used == 1
    # persisted: the dataset is now in the catalog
    assert catalog.get(ev.dataset_id) is not None


def test_gate_rejection_prevents_both_budget_spend_and_execution():
    ctx, view = _ctx(), FakeView(reject=True)
    with pytest.raises(PlanValidationError):
        mrx_fetch.fetch_evidence(_plan(), view, ctx, query="q")
    assert view.executed == 0
    assert ctx.budget.used == 0


def test_budget_exhaustion_raises_before_execution():
    ctx, view = _ctx(budget=FetchBudget(max_fetches=1)), FakeView()
    mrx_fetch.fetch_evidence(_plan(intent="first"), view, ctx, query="q")
    with pytest.raises(BudgetExhausted):
        mrx_fetch.fetch_evidence(_plan(url=VALID_URL.replace("p13=EQDELTACASH", "p13=EQGAMMACASH"),
                                       intent="second"), view, ctx, query="q")
    assert view.executed == 1  # the second never hit MRX


def test_reuse_costs_zero_budget_and_no_execution():
    ctx, view = _ctx(), FakeView()
    first = mrx_fetch.fetch_evidence(_plan(), view, ctx, query="q")
    # Same params again, fresh context in the SAME conversation -> reuse.
    ctx2 = _ctx()
    ev = mrx_fetch.fetch_evidence(_plan(), view, ctx2, query="q2")
    assert ev.provenance == "reused"
    assert ev.dataset_id == first.dataset_id
    assert ctx2.budget.used == 0
    assert view.executed == 1  # only the original fetch ever hit MRX


def test_evidence_labels_are_unique_within_a_run():
    ctx, view = _ctx(), FakeView()
    mrx_fetch.fetch_evidence(_plan(intent="same intent"), view, ctx, query="q")
    mrx_fetch.fetch_evidence(_plan(url=VALID_URL.replace("p13=EQDELTACASH", "p13=EQGAMMACASH"),
                                   intent="same intent"), view, ctx, query="q")
    labels = [e.label for e in ctx.evidence]
    assert len(labels) == len(set(labels))
