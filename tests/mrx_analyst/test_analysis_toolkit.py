"""Golden tests for the analysis ops + Tool adapters (hand-computed expectations)."""

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from mrx_analyst.core.context import Evidence, RunContext
from mrx_analyst.core.tool import run_tool
from mrx_analyst.mrx import profiler
from mrx_analyst.helpers import ops
from mrx_analyst.tools.analysis.toolkit import (
    AttributionTool, ConcentrationTool, VarianceTool, WaterfallChartTool,
    toolkit_descriptions,
)

DF = pd.DataFrame({
    "Book": ["A", "A", "B", "C"],
    "fx_vega": [900.0, 300.0, -150.0, -50.0],
})


# ---- ops (pure functions, hand-computed goldens) ---------------------------

def test_attribution_golden():
    table = ops.attribution(DF, ["Book"], "fx_vega")
    # A: 1200, B: -150, C: -50 -> net 1000; sorted by |contribution|
    assert list(table["Book"]) == ["A", "B", "C"]
    assert list(table["contribution"]) == [1200.0, -150.0, -50.0]
    assert table["share_of_net"].iloc[0] == pytest.approx(1.2)   # 1200/1000 — offsets make >100%
    assert table["share_of_net"].iloc[1] == pytest.approx(-0.15)


def test_variance_golden():
    df = pd.DataFrame({
        "Book": ["A", "B"], "cur": [100.0, 50.0], "prv": [80.0, 100.0],
    })
    table = ops.variance(df, ["Book"], "cur", "prv")
    # deltas: A +20, B -50 -> sorted by |delta|: B first
    assert list(table["Book"]) == ["B", "A"]
    assert list(table["delta"]) == [-50.0, 20.0]
    assert table["pct_change"].iloc[0] == pytest.approx(-0.5)


def test_variance_pct_is_nan_when_previous_is_zero():
    df = pd.DataFrame({"Book": ["A"], "cur": [10.0], "prv": [0.0]})
    table = ops.variance(df, ["Book"], "cur", "prv")
    assert pd.isna(table["pct_change"].iloc[0])


def test_concentration_golden():
    result = ops.concentration(DF, "Book", "fx_vega")
    # |values|: A 1200, B 150, C 50 -> total 1400
    assert result["top1_share"] == pytest.approx(1200 / 1400)
    assert result["top5_share"] == pytest.approx(1.0)
    assert result["hhi"] == pytest.approx((1200/1400)**2 + (150/1400)**2 + (50/1400)**2)


# ---- Tool adapters (label resolution + arg validation) ----------------------

def _ctx_with(df, label="fx_by_book"):
    ctx = RunContext(query="q", session_id="s")
    ctx.evidence.append(Evidence(
        dataset_id="ds1", label=label, plan=None, df=df,
        profile=profiler.profile(df), provenance="fetched",
    ))
    return ctx


def test_attribution_tool_resolves_label_and_auto_detects_value_col():
    ctx = _ctx_with(DF)
    tool = AttributionTool()
    result = run_tool(tool, tool.Args(dataset="fx_by_book", group_cols=["Book"]), ctx)
    assert list(result.value["contribution"]) == [1200.0, -150.0, -50.0]
    # the run was traced
    assert any(s.name == "attribution" for s in ctx.trace)


def test_unknown_label_is_a_clear_structured_error():
    ctx = _ctx_with(DF)
    tool = AttributionTool()
    with pytest.raises(ValueError, match="no evidence labelled"):
        run_tool(tool, tool.Args(dataset="nope", group_cols=["Book"]), ctx)
    # the failure was traced too
    assert any(s.status == "failed" for s in ctx.trace)


def test_missing_column_is_a_clear_error_listing_available():
    ctx = _ctx_with(DF)
    tool = ConcentrationTool()
    with pytest.raises(ValueError, match="not in the data"):
        run_tool(tool, tool.Args(dataset="fx_by_book", group_col="Desk"), ctx)


def test_waterfall_chart_tool_returns_a_live_figure():
    attribution_table = ops.attribution(DF, ["Book"], "fx_vega")
    ctx = _ctx_with(attribution_table, label="facts")
    tool = WaterfallChartTool()
    result = run_tool(tool, tool.Args(dataset="facts", label_col="Book",
                                      value_col="contribution", title="t"), ctx)
    assert isinstance(result.value, plt.Figure)
    assert result.value.number in plt.get_fignums()


def test_toolkit_descriptions_lists_every_tool():
    text = toolkit_descriptions()
    for name in ("attribution", "variance", "concentration",
                 "waterfall_chart", "ranked_bar_chart", "evolution_chart"):
        assert name in text
