"""The MRX simulator: live frame shapes, real-gate compatibility, stable
deterministic worlds, and — the point — a planted story the analysis
machinery provably recovers (ground-truth evals)."""

from datetime import date

import matplotlib
matplotlib.use("Agg")
import pytest

from mrx_analyst.helpers import ops
from mrx_analyst.mrx.models import MRXPlan
from mrx_analyst.mrx.sim import SimMRXView

BASE = ("https://market.risk.echonet/Market%20Risk%20Explorer/Market%20Risk%20Explorer.application"
        "?env=Production&viewid=6168&p1=GFXOPEMK&p1175=Usable&p1131=No+tracking"
        "&p1133=Perimeter+Completion&p13=FXVEGASOHO&p1016=Full+Tenors&p1201=Fixed+Tenors"
        "&p1370=Raw+Data&p1031=None&p1011=And&p1169=Standard&p1160=Y"
        "&p1144=BNP+Paribas+view+(market+risk)"
        "&p1073=CMRC%2cMetier%2cActivity%2cLocal-V%26RC%2cLocal-RiskIM")
WINDOW = "&p27=2026-07-06&p28=2026-06-08"


def _plan(extra):
    return MRXPlan(intent="t", view_reasoning="r", parameters="p", assumptions=[],
                   confidence=0.9, needs_clarification=None, SmartDF="q",
                   url=BASE + extra)


@pytest.fixture
def view():
    return SimMRXView()


def test_sim_urls_pass_the_real_validation_gate(view):
    view.validate(_plan("&p1021=Current&p1029=History+dates&p1217=RowGrpUnderlying" + WINDOW))


def test_history_frame_has_the_live_shape(view):
    df = view.execute(_plan("&p1021=Current&p1029=History+dates&p1217=RowGrpUnderlying" + WINDOW))
    assert "2026/07/06" in df.columns and "2026/06/08" in df.columns
    assert "2026/06/07" not in df.columns                     # Sunday excluded
    assert set(df["Depth"]) == {0, 1} and (df["Depth"] == 0).sum() == 1
    assert df[df.Depth == 0]["Label"].iloc[0] == "Total"


def test_compare_frame_has_total_prv_diff(view):
    df = view.execute(_plan("&p1021=Current%2cPrevious%2cDifference&p1029=Total"
                            "&p1217=RowGrpUnderlying" + WINDOW))
    assert {"Total", "Total (prv)", "Total (diff)"} <= set(df.columns)
    leaves = df[df.Depth == 1]
    assert abs(leaves["Total (diff)"].sum()
               - df[df.Depth == 0]["Total (diff)"].iloc[0]) < 1e-6


def test_filters_subset_the_labels(view):
    df = view.execute(_plan("&p1021=Current&p1029=Total&p1217=RowGrpUnderlying"
                            "&p17=USDHKD%2cUSDCNH" + WINDOW))
    assert set(df[df.Depth == 1]["Label"]) == {"USDHKD", "USDCNH"}


def test_world_is_stable_across_instances(view):
    url = "&p1021=Current&p1029=History+dates&p1217=RowGrpUnderlying" + WINDOW
    assert view.execute(_plan(url)).equals(SimMRXView().execute(_plan(url)))


def test_planted_story_is_recoverable_by_the_helpers(view):
    truth = view.truth("GFXOPEMK", "FXVEGASOHO", date(2026, 7, 6), date(2026, 6, 8))

    hist = view.execute(_plan("&p1021=Current&p1029=History+dates&p1217=RowGrpUnderlying" + WINDOW))
    t = ops.trend(hist)
    assert t["largest_jump_date"].replace("/", "-") == truth["jump_date"]

    cmp_df = view.execute(_plan("&p1021=Current%2cPrevious%2cDifference&p1029=Total"
                                "&p1217=RowGrpUnderlying" + WINDOW))
    v = ops.variance(cmp_df, ["Label"], "Total", "Total (prv)")
    assert v.iloc[0]["Label"] == truth["jump_driver"]          # ranking guaranteed
    offsets = v[v["delta"] < 0]
    assert offsets.iloc[0]["Label"] == truth["jump_offset"]


def test_explain_frame_reconciles_to_the_move(view):
    exp = view.execute(_plan("&p1021=Current%2cPrevious%2cDifference&p1029=Total"
                             "&p1217=CritPrdRiskExpain" + WINDOW))
    top = exp[exp.Depth == 0]
    assert set(top["Risk Component"]) == {"New", "Passive", "Expired"}
    hist = view.execute(_plan("&p1021=Current&p1029=History+dates&p1217=RowGrpUnderlying" + WINDOW))
    leaves = hist[hist.Depth == 1]
    move = leaves["2026/07/06"].sum() - leaves["2026/06/08"].sum()
    assert abs(top["Total (diff)"].sum() - move) / abs(move) < 0.01


def test_deal_labels_carry_maturities_for_position_change(view):
    df = view.execute(_plan("&p1021=Current%2cPrevious%2cDifference&p1029=Total"
                            "&p1217=RowGrpPrdInlNo" + WINDOW))
    labels = df[df.Depth == 1]["Label"]
    assert all("|" in l and ("Put 2" in l or "Call 2" in l) for l in labels)


def test_risk_type_grouping_is_one_row_matching_the_book_total(view):
    df = view.execute(_plan("&p1021=Current&p1029=History+dates&p1217=RowGrpRiskType" + WINDOW))
    leaves = df[df.Depth == 1]
    assert len(leaves) == 1 and leaves["Label"].iloc[0] == "FXVEGASOHO"
    by_pair = view.execute(_plan("&p1021=Current&p1029=History+dates&p1217=RowGrpUnderlying" + WINDOW))
    assert abs(leaves["2026/07/06"].iloc[0]
               - by_pair[by_pair.Depth == 1]["2026/07/06"].sum()) < 1e-6


def test_world_is_consistent_across_query_windows(view):
    """The one-day view of the jump must show the SAME move the month view
    shows for that day (the bridged run failed exactly this)."""
    month = view.execute(_plan("&p1021=Current&p1029=History+dates&p1217=RowGrpUnderlying" + WINDOW))
    leaves = month[month.Depth == 1]
    month_jump = leaves["2026/07/02"].sum() - leaves["2026/07/01"].sum()

    day = view.execute(_plan("&p1021=Current%2cPrevious%2cDifference&p1029=Total"
                             "&p1217=RowGrpUnderlying&p27=2026-07-02&p28=2026-07-01"))
    day_move = day[day.Depth == 0]["Total (diff)"].iloc[0]
    assert abs(day_move - month_jump) < 1e-6

    exp = view.execute(_plan("&p1021=Current%2cPrevious%2cDifference&p1029=Total"
                             "&p1217=CritPrdRiskExpain&p27=2026-07-02&p28=2026-07-01"))
    assert abs(exp[exp.Depth == 0]["Total (diff)"].sum() - month_jump) / abs(month_jump) < 0.01


def test_explain_respects_pair_filters(view):
    filtered = view.execute(_plan("&p1021=Current%2cPrevious%2cDifference&p1029=Total"
                                  "&p1217=CritPrdRiskExpain&p17=USDHKD%2cUSDCNH"
                                  "&p27=2026-07-02&p28=2026-07-01"))
    pair_cmp = view.execute(_plan("&p1021=Current%2cPrevious%2cDifference&p1029=Total"
                                  "&p1217=RowGrpUnderlying&p17=USDHKD%2cUSDCNH"
                                  "&p27=2026-07-02&p28=2026-07-01"))
    pair_move = pair_cmp[pair_cmp.Depth == 0]["Total (diff)"].iloc[0]
    explained = filtered[filtered.Depth == 0]["Total (diff)"].sum()
    assert abs(explained - pair_move) / abs(pair_move) < 0.01   # NOT node-wide


def test_helpers_leafify_is_public():
    from mrx_analyst.helpers import ops
    assert callable(ops.leafify)     # advertised in reading.md + tool prompt


# ---- the factored cell world: sweep ground truth --------------------------

def _cmp(view, extra):
    return view.execute(_plan("&p1021=Current%2cPrevious%2cDifference&p1029=Total"
                              + extra + WINDOW))


def test_every_dimension_cut_reconciles_to_the_same_net(view):
    nets = {}
    for code in ["RowGrpUnderlying", "RowGrpPrdDsc", "RowGrpPtfCod", "RowGrpCurrency"]:
        df = _cmp(view, f"&p1217={code}")
        nets[code] = df[df.Depth == 1]["Total (diff)"].sum()
    values = list(nets.values())
    assert all(abs(v - values[0]) < 1e-6 * max(1, abs(values[0])) for v in values), nets


def test_product_dimension_is_concentrated_books_proportional(view):
    truth = view.truth("GFXOPEMK", "FXVEGASOHO")
    prod = _cmp(view, "&p1217=RowGrpPrdDsc")
    leaves = prod[prod.Depth == 1].set_index("Label")
    move_share = (leaves["Total (diff)"].abs()
                  / leaves["Total (diff)"].abs().sum())
    book_share = leaves["Total (prv)"].abs() / leaves["Total (prv)"].abs().sum()
    divergence_prod = 0.5 * (move_share - book_share).abs().sum()

    books = _cmp(view, "&p1217=RowGrpPtfCod")
    bl = books[books.Depth == 1].set_index("Label")
    mv = bl["Total (diff)"].abs() / bl["Total (diff)"].abs().sum()
    bk = bl["Total (prv)"].abs() / bl["Total (prv)"].abs().sum()
    divergence_book = 0.5 * (mv - bk).abs().sum()

    assert divergence_prod > 0.25, divergence_prod          # the story dimension
    assert divergence_book < 0.05, divergence_book          # proportional
    assert move_share.idxmax() == truth["informative_dimensions"]["product"]["label"]


def test_cross_cut_reconciles_to_the_filtered_slice(view):
    # by underlying, filtered to FX Target == the FX Target row of the product cut
    prod = _cmp(view, "&p1217=RowGrpPrdDsc")
    target_row = prod[(prod.Depth == 1) & (prod.Label == "FX Target")].iloc[0]
    cross = _cmp(view, "&p1217=RowGrpUnderlying&p17=FX+Target")
    cross_net = cross[cross.Depth == 1]["Total (diff)"].sum()
    assert abs(cross_net - target_row["Total (diff)"]) < 1e-6 * max(1, abs(cross_net))
    # and the jump inside the FX Target slice is USDHKD-led
    top = cross[cross.Depth == 1].sort_values("Total (diff)", ascending=False).iloc[0]
    assert top["Label"] == "USDHKD"


def test_deal_cut_partitions_the_slice(view):
    cross = _cmp(view, "&p1217=RowGrpUnderlying&p17=FX+Target")
    deals = _cmp(view, "&p1217=RowGrpPrdInlNo&p17=FX+Target")
    a = cross[cross.Depth == 1]["Total (diff)"].sum()
    b = deals[deals.Depth == 1]["Total (diff)"].sum()
    assert abs(a - b) < 1e-6 * max(1, abs(a))


def test_truth_names_informative_and_diffuse_dimensions(view):
    truth = view.truth("GFXOPEMK", "FXVEGASOHO")
    assert truth["informative_dimensions"]["underlying"]["label"] == "USDHKD"
    assert truth["informative_dimensions"]["product"]["label"] == "FX Target"
    assert "book" in truth["diffuse_dimensions"]


def test_sweep_diagnostics_recovers_the_planted_dimensions(view):
    from mrx_analyst.helpers import ops
    frames = {dim: _cmp(view, f"&p1217={code}") for dim, code in [
        ("underlying", "RowGrpUnderlying"), ("product", "RowGrpPrdDsc"),
        ("portfolio", "RowGrpPtfCod"), ("currency", "RowGrpCurrency")]}
    out = ops.sweep_diagnostics(frames)
    ranked = list(out["table"]["dimension"])
    assert set(ranked[:2]) == {"underlying", "product"}, ranked
    assert ranked[-2:] and set(ranked[-2:]) <= {"portfolio", "currency"}
    assert out["reconciled"]
    t = out["table"].set_index("dimension")
    assert t.loc["product", "top1_label"] == "FX Target"
    assert t.loc["underlying", "top1_label"] == "USDHKD"
