import pandas as pd

from mrx import catalog
from mrx.generate_link import MRXPlan

VALID_URL = (
    "https://market.risk.echonet/Market%20Risk%20Explorer/Market%20Risk%20Explorer.application"
    "?env=Production&viewid=6168&p1=EQDUSNLH&p1021=Current&p1029=Total"
    "&p1217=RowGrpRiskType&p1175=Usable&p1131=No+tracking&p1133=Perimeter+Completion"
    "&p27=2024-11-01&p28=2024-10-31&p13=EQDELTACASH"
)


def _plan(**overrides):
    defaults = dict(
        intent="test intent", view_reasoning="r", parameters="p", assumptions=[],
        confidence=0.95, needs_clarification=None, SmartDF="What is the average value?",
        url=VALID_URL,
    )
    defaults.update(overrides)
    return MRXPlan(**defaults)


def _dataset(**overrides):
    defaults = dict(
        id=catalog.new_dataset_id(),
        session_id="sess1",
        query="what is the average value",
        plan=_plan(),
        created_at="2026-07-01T00:00:00+00:00",
        description="a test dataset",
        schema={"value": "int64"},
    )
    defaults.update(overrides)
    return catalog.Dataset(**defaults)


def test_save_and_load_df_round_trips_dtypes_exactly(tmp_catalog):
    df = pd.DataFrame({"value": [1, 2, 3], "name": ["a", "b", "c"], "amount": [1.5, 2.5, 3.5]})
    dataset = _dataset()

    catalog.save(dataset, df)
    loaded = catalog.load_df(dataset.id)

    assert loaded.equals(df)
    assert dict(loaded.dtypes) == dict(df.dtypes)


def test_get_returns_stored_metadata(tmp_catalog):
    dataset = _dataset(description="FX Vega by desk")
    catalog.save(dataset, pd.DataFrame({"value": [1]}))

    fetched = catalog.get(dataset.id)

    assert fetched.id == dataset.id
    assert fetched.query == dataset.query
    assert fetched.description == "FX Vega by desk"
    assert fetched.plan.url == VALID_URL


def test_get_returns_none_for_unknown_id(tmp_catalog):
    assert catalog.get("ds_does_not_exist") is None


def test_load_df_raises_for_unknown_id(tmp_catalog):
    import pytest
    with pytest.raises(FileNotFoundError):
        catalog.load_df("ds_does_not_exist")


def test_list_all_ranks_own_session_first(tmp_catalog):
    own = _dataset(id="ds_own", session_id="sess1", created_at="2026-07-01T00:00:00+00:00")
    other = _dataset(id="ds_other", session_id="sess2", created_at="2026-07-01T01:00:00+00:00")
    # `other` is more recent, but should still rank after sess1's own datasets.
    catalog.save(own, pd.DataFrame({"value": [1]}))
    catalog.save(other, pd.DataFrame({"value": [2]}))

    results = catalog.list_all(session_id="sess1")

    assert [d.id for d in results] == ["ds_own", "ds_other"]


def test_list_all_is_team_wide_not_scoped_out(tmp_catalog):
    # A dataset created under a different session must still be visible —
    # this is a confirmed team-wide shared store, not per-user isolation.
    other = _dataset(id="ds_other", session_id="some_other_analyst")
    catalog.save(other, pd.DataFrame({"value": [1]}))

    results = catalog.list_all(session_id="me")

    assert len(results) == 1
    assert results[0].id == "ds_other"


def test_list_all_empty_catalog_returns_empty_list(tmp_catalog):
    assert catalog.list_all(session_id="anyone") == []
