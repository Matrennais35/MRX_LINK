"""Golden tests for the two answer-quality ops, on the eval's REAL shapes:
trend on a Q1-style wide daily series (the dropped 'jump dates' analysis),
position_change on the Q3 pattern (prev=0 paired legs — the new-trade build).
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

from mrx_analyst.helpers import ops


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
    # The eval's Q3 pattern: paired new legs (prev=0), an expired leg (maturity
    # in the label, before the as_of date), an unwound leg (no maturity),
    # existing moves.
    return pd.DataFrame({
        "Deal/Security": ["FXO-1/4", "FXO-1/3", "FXO-2/1",
                          "FXO-old | Put 2026-06-15", "FXO-cut", "FXO-exist"],
        "2026/07/03": [2_478_894.0, -2_478_894.0, 1_888_907.0, 0.0, 0.0, 1_471_818.0],
        "2026/06/03": [0.0, 0.0, 0.0, 961_890.0, 120_000.0, -361_836.0],
    })


def test_position_change_buckets_new_expired_unwound_existing():
    result = ops.position_change(_q3_deals(), ["Deal/Security"],
                                 "2026/07/03", "2026/06/03")
    summary = result["table"].set_index("bucket")
    # NEW: the two paired legs net to zero + FXO-2/1
    assert summary.loc["new", "positions"] == 3
    assert summary.loc["new", "delta"] == pytest.approx(1_888_907)
    # EXPIRED: FXO-old's label maturity (2026-06-15) <= as_of (2026-07-03)
    assert summary.loc["expired", "delta"] == pytest.approx(-961_890)
    # UNWOUND: FXO-cut disappeared with no maturity in its label
    assert summary.loc["unwound", "delta"] == pytest.approx(-120_000)
    # EXISTING: FXO-exist revalued
    assert summary.loc["existing", "delta"] == pytest.approx(1_471_818 + 361_836)
    assert result["net"] == pytest.approx(1_888_907 - 961_890 - 120_000 + 1_833_654)


def test_position_change_detail_names_the_top_contributors_per_bucket():
    result = ops.position_change(_q3_deals(), ["Deal/Security"],
                                 "2026/07/03", "2026/06/03", top_n=2)
    detail = result["tables"]["position_detail"]
    new_rows = detail[detail["bucket"] == "new"]
    assert len(new_rows) == 2                                # capped at top_n
    assert abs(new_rows.iloc[0]["delta"]) >= abs(new_rows.iloc[1]["delta"])


# ---- sweep_diagnostics: divergence separates story from proportional -------

def _cmp_frame(labels, prev, cur):
    import pandas as pd
    df = pd.DataFrame({"Label": labels, "Total (prv)": prev, "Total": cur})
    df["Total (diff)"] = df["Total"] - df["Total (prv)"]
    return df


def test_sweep_ranks_concentrated_dimension_above_proportional():
    # product: book 60/30/10 but the ENTIRE +100 move in the smallest product
    product = _cmp_frame(["A", "B", "C"], [600.0, 300.0, 100.0],
                         [600.0, 300.0, 200.0])
    # book: everything moves +10% — proportional, top1 share of move is 60%!
    book = _cmp_frame(["X", "Y", "Z"], [600.0, 300.0, 100.0],
                      [660.0, 330.0, 110.0])
    out = ops.sweep_diagnostics({"product": product, "book": book})
    t = out["table"].set_index("dimension")
    assert out["top_dimension"] == "product"
    assert t.loc["product", "divergence"] > 0.5
    assert t.loc["book", "divergence"] < 0.01          # despite top1_share 60%
    assert t.loc["book", "top1_share_gross"] > 0.55    # the trap the metric avoids
    assert t.loc["product", "top1_label"] == "C"
    assert out["reconciled"]


def test_sweep_quarantines_non_reconciling_dimension():
    good1 = _cmp_frame(["A", "B"], [100.0, 200.0], [150.0, 250.0])   # net +100
    good2 = _cmp_frame(["X", "Y"], [30.0, 270.0], [80.0, 320.0])     # net +100
    bad = _cmp_frame(["K"], [100.0], [130.0])                        # net +30
    out = ops.sweep_diagnostics({"d1": good1, "d2": good2, "broken": bad})
    recon = out["tables"]["reconciliation"].set_index("dimension")
    assert bool(recon.loc["d1", "ok"]) and bool(recon.loc["d2", "ok"])
    assert not bool(recon.loc["broken", "ok"])
    assert not out["reconciled"]
    assert out["top_dimension"] in ("d1", "d2")        # broken never wins


def test_sweep_handles_depth_hierarchy_and_total_rows():
    import pandas as pd
    df = pd.DataFrame({
        "Depth": [0, 1, 1], "Label": ["Total", "A", "B"],
        "Total (prv)": [300.0, 100.0, 200.0], "Total": [340.0, 140.0, 200.0],
        "Total (diff)": [40.0, 40.0, 0.0]})
    out = ops.sweep_diagnostics({"dim": df})
    assert out["table"].iloc[0]["n_rows"] == 2         # Total row excluded
    assert abs(out["reference_net"] - 40.0) < 1e-9
