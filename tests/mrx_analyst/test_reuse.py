from mrx_analyst.storage import catalog
from mrx_analyst.mrx import reuse as router
from mrx_analyst.mrx.models import MRXPlan
from mrx_analyst.mrx.view import MultirowView

# The reuse gate is now fingerprint-based (view-agnostic): the active view
# supplies fingerprint(plan) -> params. These tests exercise it with the real
# multirow fingerprint, so they still cover the exact MRX param-matching logic
# they always did.
_fp = MultirowView().fingerprint

BASE_URL = (
    "https://market.risk.echonet/Market%20Risk%20Explorer/Market%20Risk%20Explorer.application"
    "?env=Production&viewid=6168&p1=EQDUSNLH&p1021=Current&p1029=Total"
    "&p1175=Usable&p1131=No+tracking&p1133=Perimeter+Completion"
    "&p13=EQDELTACASH&p1217=RowGrpRiskType"
)


def _url(**overrides):
    params = {"p27": "2026-06-30", "p28": "2026-06-01"}
    params.update(overrides)
    return BASE_URL + "".join(f"&{k}={v}" for k, v in params.items())


def _plan(url):
    return MRXPlan(
        intent="test", view_reasoning="r", parameters="p", assumptions=[],
        confidence=0.95, needs_clarification=None, SmartDF="q", url=url,
    )


def _dataset(url, **overrides):
    defaults = dict(
        id=catalog.new_dataset_id(),
        session_id="sess1",
        conversation_id="conv1",
        query="original question",
        plan=_plan(url),
        created_at="2026-07-01T00:00:00+00:00",
        description="a stored dataset",
        schema={"value": "int64"},
    )
    defaults.update(overrides)
    return catalog.Dataset(**defaults)


def test_reuse_when_dimensions_and_dates_match_exactly():
    dataset = _dataset(_url(p27="2026-06-30", p28="2026-06-01"))
    new_url = _url(p27="2026-06-30", p28="2026-06-01")

    hit = router.find_reusable_dataset([dataset], _plan(new_url), fingerprint=_fp)

    assert hit is dataset


def test_reuse_when_stored_range_is_a_superset_of_the_new_question():
    # Stored dataset covers all of June; new question only needs the first week.
    dataset = _dataset(_url(p27="2026-06-30", p28="2026-06-01"))
    new_url = _url(p27="2026-06-07", p28="2026-06-01")

    hit = router.find_reusable_dataset([dataset], _plan(new_url), fingerprint=_fp)

    assert hit is dataset


def test_no_reuse_when_new_question_needs_dates_outside_stored_range():
    # "what about last week" after a dataset that only covers June.
    dataset = _dataset(_url(p27="2026-06-30", p28="2026-06-01"))
    new_url = _url(p27="2026-07-15", p28="2026-07-08")

    hit = router.find_reusable_dataset([dataset], _plan(new_url), fingerprint=_fp)

    assert hit is None


def test_no_reuse_when_risk_type_differs():
    dataset = _dataset(_url().replace("p13=EQDELTACASH", "p13=FXVEGASOHO"))
    new_url = _url()  # p13=EQDELTACASH

    hit = router.find_reusable_dataset([dataset], _plan(new_url), fingerprint=_fp)

    assert hit is None


def test_no_reuse_when_row_grouping_differs():
    # "split by top deals" changes the row-level grouping param — must NOT
    # be silently reused just because risk type/node/dates all match.
    dataset = _dataset(_url())  # p1217=RowGrpRiskType
    new_url = _url().replace("p1217=RowGrpRiskType", "p1218=CritDealCLC")

    hit = router.find_reusable_dataset([dataset], _plan(new_url), fingerprint=_fp)

    assert hit is None


def test_no_reuse_when_result_layout_differs():
    # p1029 controls result layout (e.g. "Total" point-in-time snapshot vs.
    # a wide history-dates series) — a stored wide series must NOT be reused
    # for a snapshot request just because risk type/node/dates all match.
    # This was previously missed: the old allowlist only checked risk type,
    # node, and row grouping, never result-shape params like this one.
    dataset = _dataset(_url())  # p1029=Total
    new_url = _url().replace("p1029=Total", "p1029=HistoryDates")

    hit = router.find_reusable_dataset([dataset], _plan(new_url), fingerprint=_fp)

    assert hit is None


def test_no_reuse_when_current_vs_comparison_mode_differs():
    # p1021 controls Current vs. Current/Previous/Difference (1 vs. up to 3
    # value columns) — also previously missed by the old allowlist.
    dataset = _dataset(_url())  # p1021=Current
    new_url = _url().replace("p1021=Current", "p1021=CurrentPreviousDifference")

    hit = router.find_reusable_dataset([dataset], _plan(new_url), fingerprint=_fp)

    assert hit is None


def test_reuse_still_works_when_an_unlisted_param_is_added_on_both_sides():
    # The deny-list approach (only dates may differ) should still correctly
    # allow reuse when a new/unanticipated param is present and IDENTICAL
    # on both sides — proving this isn't accidentally over-strict.
    dataset = _dataset(_url() + "&p1160=Y")
    new_url = _url(p27="2026-06-07", p28="2026-06-01") + "&p1160=Y"

    hit = router.find_reusable_dataset([dataset], _plan(new_url), fingerprint=_fp)

    assert hit is dataset


def test_no_reuse_when_urls_are_unparseable():
    dataset = _dataset("not-a-valid-url")
    new_url = _url()

    hit = router.find_reusable_dataset([dataset], _plan(new_url), fingerprint=_fp)

    assert hit is None


def test_find_reusable_dataset_picks_first_qualifying_from_ranked_list():
    # catalog.list_all already ranks by session-then-recency; the router
    # just takes the first match, it doesn't re-rank.
    no_match = _dataset(_url(p27="2026-05-31", p28="2026-05-01"), id="ds_no_match")
    match = _dataset(_url(p27="2026-06-30", p28="2026-06-01"), id="ds_match")
    new_url = _url(p27="2026-06-30", p28="2026-06-01")

    hit = router.find_reusable_dataset([no_match, match], _plan(new_url), fingerprint=_fp)

    assert hit.id == "ds_match"


def test_find_reusable_dataset_returns_none_for_empty_catalog():
    assert router.find_reusable_dataset([], _plan(_url()), fingerprint=_fp) is None
