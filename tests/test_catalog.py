import subprocess
import sys

import pandas as pd

from mrx.pipeline import catalog
from mrx.pipeline.models import MRXPlan

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


def test_save_derives_schema_from_df_when_not_explicitly_given(tmp_catalog):
    # catalog.save() should compute the schema itself from `df` (which it
    # has in scope) rather than requiring the caller to independently
    # replicate the same {col: str(dtype)} computation and risk drift.
    df = pd.DataFrame({"value": [1, 2, 3], "name": ["a", "b", "c"], "amount": [1.5, 2.5, 3.5]})
    dataset = _dataset(schema=None)

    catalog.save(dataset, df)
    stored = catalog.get(dataset.id)

    assert stored.schema == {col: str(dtype) for col, dtype in df.dtypes.items()}


def test_save_still_honors_an_explicitly_given_schema(tmp_catalog):
    dataset = _dataset(schema={"custom": "override"})
    catalog.save(dataset, pd.DataFrame({"value": [1]}))

    stored = catalog.get(dataset.id)

    assert stored.schema == {"custom": "override"}


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


def _turn(**overrides):
    defaults = dict(
        id=catalog.new_turn_id(),
        conversation_id="conv1",
        created_at="2026-07-01T00:00:00+00:00",
        question="What is the average value?",
        narration="The average value is 2.",
        method="Computed the mean of the value column.",
        answer_type="number",
        value_preview="2.0",
        code='result = {"type": "number", "value": df["value"].mean()}',
    )
    defaults.update(overrides)
    return catalog.Turn(**defaults)


def test_save_and_list_turns_round_trips(tmp_catalog):
    turn = _turn()
    catalog.save_turn(turn)

    turns = catalog.list_turns(conversation_id="conv1")

    assert len(turns) == 1
    assert turns[0].id == turn.id
    assert turns[0].question == "What is the average value?"
    assert turns[0].narration == "The average value is 2."
    assert turns[0].answer_type == "number"
    assert turns[0].value_preview == "2.0"


def test_list_turns_orders_oldest_first(tmp_catalog):
    first = _turn(id="turn_1", created_at="2026-07-01T00:00:00+00:00", question="first question")
    second = _turn(id="turn_2", created_at="2026-07-01T00:05:00+00:00", question="second question")
    # Save in reverse order — the ORDER BY must be what determines output order, not insert order.
    catalog.save_turn(second)
    catalog.save_turn(first)

    turns = catalog.list_turns(conversation_id="conv1")

    assert [t.question for t in turns] == ["first question", "second question"]


def test_list_turns_scoped_to_one_conversation(tmp_catalog):
    catalog.save_turn(_turn(id="turn_a", conversation_id="conv_a"))
    catalog.save_turn(_turn(id="turn_b", conversation_id="conv_b"))

    turns = catalog.list_turns(conversation_id="conv_a")

    assert len(turns) == 1
    assert turns[0].id == "turn_a"


def test_list_turns_empty_conversation_returns_empty_list(tmp_catalog):
    assert catalog.list_turns(conversation_id="nonexistent") == []


def test_list_conversations_summarizes_each_conversation(tmp_catalog):
    catalog.save_turn(_turn(
        id="t1", conversation_id="conv_a", created_at="2026-07-01T00:00:00+00:00",
        question="first question in conv_a",
    ))
    catalog.save_turn(_turn(
        id="t2", conversation_id="conv_a", created_at="2026-07-01T00:05:00+00:00",
        question="second question in conv_a",
    ))
    catalog.save_turn(_turn(
        id="t3", conversation_id="conv_b", created_at="2026-07-01T00:02:00+00:00",
        question="only question in conv_b",
    ))

    summaries = catalog.list_conversations()

    assert len(summaries) == 2
    by_id = {s.conversation_id: s for s in summaries}
    assert by_id["conv_a"].turn_count == 2
    assert by_id["conv_a"].first_question == "first question in conv_a"
    assert by_id["conv_a"].last_activity_at == "2026-07-01T00:05:00+00:00"
    assert by_id["conv_b"].turn_count == 1
    assert by_id["conv_b"].first_question == "only question in conv_b"


def test_list_conversations_orders_most_recently_active_first(tmp_catalog):
    catalog.save_turn(_turn(id="t1", conversation_id="conv_old", created_at="2026-07-01T00:00:00+00:00"))
    catalog.save_turn(_turn(id="t2", conversation_id="conv_new", created_at="2026-07-01T05:00:00+00:00"))

    summaries = catalog.list_conversations()

    assert [s.conversation_id for s in summaries] == ["conv_new", "conv_old"]


def test_list_conversations_respects_limit(tmp_catalog):
    for i in range(5):
        catalog.save_turn(_turn(
            id=f"t{i}", conversation_id=f"conv_{i}",
            created_at=f"2026-07-01T00:0{i}:00+00:00",
        ))

    summaries = catalog.list_conversations(limit=2)

    assert len(summaries) == 2
    # The 2 most recent by last_activity_at.
    assert [s.conversation_id for s in summaries] == ["conv_4", "conv_3"]


def test_list_conversations_empty_catalog_returns_empty_list(tmp_catalog):
    assert catalog.list_conversations() == []


def test_catalog_module_imports_without_pymrx_installed():
    # Regression test: catalog.py is pure storage code and must not require
    # the internal `pymrx` package to be importable. It previously did,
    # transitively — generate_link.py (which catalog.py imported MRXPlan
    # from, before MRXPlan moved to mrx.pipeline.models) had an unused
    # `import pymrx` at module scope. conftest.py stubs pymrx globally for
    # every other test in this suite, so that regression would otherwise go
    # undetected here — this spawns a real, separate interpreter with pymrx
    # genuinely absent (not just unstubbed) to verify the claim durably.
    result = subprocess.run(
        [sys.executable, "-c", "import mrx.pipeline.catalog"],
        cwd=str(catalog.BASE_DIR),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "pymrx" not in result.stderr
