"""Golden tests for the two answer-quality ops, on the eval's REAL shapes:
trend on a Q1-style wide daily series (the dropped 'jump dates' analysis),
position_change on the Q3 pattern (prev=0 paired legs — the new-trade build).
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

from mrx_analyst.core.context import Evidence, RunContext
from mrx_analyst.core.tool import run_tool
from mrx_analyst.tools import profiler
from mrx_analyst.tools.analysis import ops
from mrx_analyst.tools.analysis.toolkit import (
    PositionChangeTool, TrendTool, toolkit_descriptions,
)


# ---- trend ---------------------------------------------------------------------

def _q1_series():
    # The eval's 1x24 aggregate frame, reduced: flat, one step, then a jump.
    return pd.DataFrame({
        "Risk Type": ["FX Vega"],
        "2026/06/03": [6_480_000.0],
        "2026/06/10": [6_500_000.0],
        "2026/06/17": [6_520_000.0],
        "2026/06/24": [9_620_000.0],   # +3.1m step
        "2026/07/01": [12_020_000.0],  # +2.4m step
        "2026/07/03": [13_800_000.0],
    })


def test_trend_dates_the_jumps_and_anchors_start_end():
    result = ops.trend(_q1_series(), top_jumps=2)
    assert result["start"] == pytest.approx(6_480_000)
    assert result["end"] == pytest.approx(13_800_000)
    assert result["net"] == pytest.approx(7_320_000)
    assert result["largest_jump_date"] == "2026/06/24"      # the +3.1m day, DATED
    jump_dates = set(result["table"]["Date"])
    assert {"2026/06/24", "2026/07/01"} <= jump_dates        # both steps present
    assert {"2026/06/03", "2026/07/03"} <= jump_dates        # anchors present


def test_trend_returns_the_chartable_long_series():
    result = ops.trend(_q1_series())
    series = result["tables"]["trend_series"]
    assert list(series.columns) == ["Date", "Value"]
    assert len(series) == 6
    assert series["Date"].is_monotonic_increasing


def test_trend_sums_leaf_rows_only_under_depth():
    df = _q1_series()
    df = pd.concat([df, df], ignore_index=True)
    df.insert(0, "Depth", [1, 2])                            # row 0 duplicates row 1
    result = ops.trend(df)
    assert result["end"] == pytest.approx(13_800_000)        # not doubled


def test_trend_rejects_frames_without_date_columns():
    with pytest.raises(ValueError, match="date-named columns"):
        ops.trend(pd.DataFrame({"a": [1.0], "b": [2.0]}))


# ---- position_change -------------------------------------------------------------

def _q3_deals():
    # The eval's Q3 pattern: paired new legs (prev=0), a closed leg, existing moves.
    return pd.DataFrame({
        "Deal/Security": ["FXO-1/4", "FXO-1/3", "FXO-2/1", "FXO-old", "FXO-exist"],
        "2026/07/03": [2_478_894.0, -2_478_894.0, 1_888_907.0, 0.0, 1_471_818.0],
        "2026/06/03": [0.0, 0.0, 0.0, 961_890.0, -361_836.0],
    })


def test_position_change_buckets_new_closed_existing():
    result = ops.position_change(_q3_deals(), ["Deal/Security"],
                                 "2026/07/03", "2026/06/03")
    summary = result["table"].set_index("bucket")
    # NEW: the two paired legs net to zero + FXO-2/1
    assert summary.loc["new", "positions"] == 3
    assert summary.loc["new", "delta"] == pytest.approx(1_888_907)
    # CLOSED: FXO-old disappeared
    assert summary.loc["closed", "delta"] == pytest.approx(-961_890)
    # EXISTING: FXO-exist revalued
    assert summary.loc["existing", "delta"] == pytest.approx(1_471_818 + 361_836)
    assert result["net"] == pytest.approx(1_888_907 - 961_890 + 1_833_654)


def test_position_change_detail_names_the_top_contributors_per_bucket():
    result = ops.position_change(_q3_deals(), ["Deal/Security"],
                                 "2026/07/03", "2026/06/03", top_n=2)
    detail = result["tables"]["position_detail"]
    new_rows = detail[detail["bucket"] == "new"]
    assert len(new_rows) == 2                                # capped at top_n
    assert abs(new_rows.iloc[0]["delta"]) >= abs(new_rows.iloc[1]["delta"])


# ---- adapters: registered side-tables reach the evidence -------------------------

def _ctx_with(df, label):
    ctx = RunContext(query="q", session_id="s")
    ctx.evidence.append(Evidence(dataset_id=label, label=label, plan=None, df=df,
                                 profile=profiler.profile(df), provenance="fetched"))
    return ctx


def test_trend_tool_summary_carries_the_dated_move():
    ctx = _ctx_with(_q1_series(), "daily_series")
    tool = TrendTool()
    result = run_tool(tool, tool.Args(dataset="daily_series"), ctx)
    assert "2026/06/24" in result.summary                    # the dated jump, in the trace


def test_new_ops_are_on_the_analyst_menu():
    text = toolkit_descriptions()
    assert "trend" in text and "position_change" in text
    assert "trend_series" in text                            # the chaining hint
