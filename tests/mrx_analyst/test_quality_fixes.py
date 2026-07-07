"""Regression tests for the answer-quality fixes, with fixtures replicating the
REAL frames from the live eval (eval.md): wide History-dates frames, Depth
hierarchies with duplicated ancestor sums, MRX's 'Invalid Parameters' response,
and the Analyst's prepare-then-operate pattern that used to fail.
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

from mrx_analyst.execute.session import FetchBudget, ToolSession
from mrx_analyst.common.errors import DataFetchError
from mrx_analyst.mrx.models import MRXPlan
from mrx_analyst.mrx import profiler
from mrx_analyst.execute.tools import fetch_mrx as mrx_fetch
from mrx_analyst.helpers import ops


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
    ctx = ToolSession(session_id="s", budget=FetchBudget(max_fetches=2))
    plan = MRXPlan(intent="i", view_reasoning="r", parameters="p", assumptions=[],
                   confidence=0.9, needs_clarification=None, SmartDF="q", url=VALID_URL)
    with pytest.raises(DataFetchError) as exc:
        mrx_fetch.fetch_evidence(plan, _InvalidParamsView(), ctx, query="q")
    assert exc.value.url == VALID_URL                   # the scout gets the URL to fix
    assert ctx.evidence == []                            # never polluted the evidence


# ---- rendering: NaN in computed tables must not crash the report --------------

def test_format_number_renders_nan_as_dash_not_crash():
    import numpy as np
    from mrx_analyst.ui.format import format_number, format_numeric_columns
    assert format_number(float("nan")) == "—"
    assert format_number(None) == "—"
    assert format_number(1234567.89) == "1,234,568"
    # the real crash shape: the trend jumps table's NaN first-row Change
    df = pd.DataFrame({"Date": ["2026/06/01", "2026/06/04"],
                       "Value": [-951388.0, -426425.0],
                       "Change": [np.nan, 971704.0]})
    rendered = format_numeric_columns(df)
    assert rendered["Change"].iloc[0] == "—"
    assert rendered["Change"].iloc[1] == "971,704"
