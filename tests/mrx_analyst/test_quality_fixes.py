"""Regression tests for the answer-quality fixes, with fixtures replicating the
REAL frames from the live eval (eval.md): wide History-dates frames, Depth
hierarchies with duplicated ancestor sums, MRX's 'Invalid Parameters' response,
and the Analyst's prepare-then-operate pattern that used to fail.
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

from mrx_analyst.core.context import FetchBudget, RunContext
from mrx_analyst.core.errors import DataFetchError
from mrx_analyst.core.models import MRXPlan
from mrx_analyst.tools import mrx_fetch, profiler
from mrx_analyst.tools.analysis import ops


# ---- profiler: wide History-dates frames (the eval's blind-drill cause) ------

def _wide_frame():
    # Shape of the eval's 107x24 underlying frame, reduced: label + date columns.
    return pd.DataFrame({
        "Underlying": ["USDHKD", "USDCNH", "EURUSD"],
        "2026/06/03": [1_442_596.0, 1_104_375.0, 3_014_276.0],
        "2026/06/17": [437_606.0, 1_886_834.0, 507_200.0],
        "2026/07/03": [6_647_673.0, 3_124_116.0, 1_161_594.0],
    })


def test_wide_date_frame_is_measured_on_the_latest_date_column():
    p = profiler.profile(_wide_frame())
    assert p.wide_measured_on == "2026/07/03"
    assert p.value_columns == ["2026/07/03"]
    assert p.total_sum == pytest.approx(6_647_673 + 3_124_116 + 1_161_594)
    # the scout can now SEE who dominates
    assert "USDHKD" in p.top_movers[0]["label"]


def test_wide_date_frame_exposes_first_to_last_delta_movers():
    p = profiler.profile(_wide_frame())
    # deltas: USDHKD +5,205,077; USDCNH +2,019,741; EURUSD -1,852,682
    assert p.delta_net == pytest.approx(5_205_077 + 2_019_741 - 1_852_682)
    assert "USDHKD" in p.top_delta_movers[0]["label"]
    assert p.top_delta_movers[0]["value"] == pytest.approx(5_205_077)
    text = p.render_text()
    assert "first->last delta" in text


# ---- profiler + ops: Depth hierarchies (the eval's double-count) --------------

def _depth_frame():
    # Ancestor (Depth 1) duplicates its two children (Depth 2) — the eval's
    # Q10 shape where rows 0 and 1 both carried 17,430,388.
    return pd.DataFrame({
        "Depth": [1, 2, 2, 1, 2],
        "Underlying": ["ASIA", "USDHKD", "USDCNH", "G10", "EURUSD"],
        "value": [900.0, 600.0, 300.0, 100.0, 100.0],
    })


def test_profiler_excludes_depth_ancestors_and_never_picks_depth_as_value():
    p = profiler.profile(_depth_frame())
    assert p.hierarchy_ancestors_excluded == 2          # ASIA + G10
    assert p.value_columns == ["value"]                  # NOT Depth
    assert p.total_sum == pytest.approx(600 + 300 + 100)  # leaf-only, no double count
    assert "Depth-ancestor" in p.render_text()


def test_ops_group_over_leaf_rows_only():
    table = ops.attribution(_depth_frame(), ["Underlying"], "value", top_n=10)
    # Ancestors must not appear or inflate: leaves sum to 1000, not 2000.
    assert table["contribution"].sum() == pytest.approx(1000.0)
    assert "ASIA" not in set(table["Underlying"])


# ---- mrx_fetch: MRX's silent 'Invalid Parameters' response --------------------

VALID_URL = (
    "https://market.risk.echonet/Market%20Risk%20Explorer/Market%20Risk%20Explorer.application"
    "?env=Production&viewid=6168&p1=GFXOPEMK&p27=2026-07-03&p28=2026-07-02&p13=EQDELTACASH"
)


class _InvalidParamsView:
    name = "fake"

    def validate(self, plan, **kw):
        pass

    def execute(self, plan):
        return pd.DataFrame({"Invalid Parameters": ["see MRX"]})   # the real 1x1 shape

    def fingerprint(self, plan):
        from urllib.parse import parse_qsl, urlparse
        return dict(parse_qsl(urlparse(plan.url).query))


def test_invalid_parameters_response_raises_instead_of_becoming_evidence():
    ctx = RunContext(query="q", session_id="s", budget=FetchBudget(max_fetches=2))
    plan = MRXPlan(intent="i", view_reasoning="r", parameters="p", assumptions=[],
                   confidence=0.9, needs_clarification=None, SmartDF="q", url=VALID_URL)
    with pytest.raises(DataFetchError) as exc:
        mrx_fetch.fetch_evidence(plan, _InvalidParamsView(), ctx, query="q")
    assert exc.value.url == VALID_URL                   # the scout gets the URL to fix
    assert ctx.evidence == []                            # never polluted the evidence


# ---- orchestrator: prepare-then-operate execution (the eval's #1 defect) ------

def test_declared_fallback_runs_first_and_registers_named_tables(monkeypatch):
    """The Q6 pattern: ops reference 'facts' that the fallback creates. Old
    order failed the op and burned a retry; new order works in ONE proposal."""
    from mrx_analyst.agents.analyst import AnalysisSpec, ToolkitCall
    from mrx_analyst.core import orchestrator

    long_table = pd.DataFrame({"COB Date": ["2026-06-23", "2026-07-03"],
                               "Total": [708_600.0, 688_800.0]})

    def fake_generate_and_run(llm, datasets, request, **kw):
        return {"type": "composed",
                "value": {"table": long_table, "chart": None,
                          "tables": {"prepared_series": long_table}},
                "code": "melted = ..."}

    monkeypatch.setattr(orchestrator.codegen, "generate_and_run", fake_generate_and_run)

    ctx = RunContext(query="plot the evolution", session_id="s")
    spec = AnalysisSpec(
        reasoning="reshape first, then chart",
        ops=[ToolkitCall(tool="evolution_chart",
                         args_json='{"dataset": "facts", "x_col": "COB Date", "y_col": "Total"}')],
        fallback_code_request="melt the wide frame into COB Date/Total",
    )
    facts = orchestrator._execute_spec(llm=None, spec=spec, ctx=ctx)

    assert facts.table is long_table                     # fallback's primary table
    assert facts.chart is not None                       # op consumed 'facts' and charted it
    assert any(e.label == "prepared_series" for e in ctx.evidence)  # named intermediate registered
    # exactly one codegen run, zero failed ops
    assert not any(s.status == "failed" for s in ctx.trace)


def test_op_failure_after_successful_fallback_keeps_the_computed_facts(monkeypatch):
    """A bad op no longer throws away good computation (no full retry)."""
    from mrx_analyst.agents.analyst import AnalysisSpec, ToolkitCall
    from mrx_analyst.core import orchestrator

    table = pd.DataFrame({"a": [1.0]})
    monkeypatch.setattr(orchestrator.codegen, "generate_and_run",
                        lambda llm, d, r, **kw: {"type": "dataframe", "value": table, "code": "c"})

    ctx = RunContext(query="q", session_id="s")
    spec = AnalysisSpec(
        reasoning="r",
        ops=[ToolkitCall(tool="ranked_bar_chart",
                         args_json='{"dataset": "facts", "label_col": "MISSING", "value_col": "a"}')],
        fallback_code_request="compute the table",
    )
    facts = orchestrator._execute_spec(llm=None, spec=spec, ctx=ctx)
    assert facts.table is table                          # kept despite the failed op
    assert any(s.status == "failed" for s in ctx.trace)  # and the failure is traced


# ---- codegen contract: named tables validation ---------------------------------

def test_composed_result_accepts_and_validates_named_tables():
    from mrx_analyst.tools.codegen import _validate_composed
    good = {"table": pd.DataFrame({"a": [1]}), "chart": None,
            "tables": {"extra": pd.DataFrame({"b": [2]})}}
    _validate_composed(good)                             # no raise

    bad = {"table": pd.DataFrame({"a": [1]}), "chart": None, "tables": {"x": 42}}
    with pytest.raises(ValueError, match="name -> DataFrame"):
        _validate_composed(bad)
