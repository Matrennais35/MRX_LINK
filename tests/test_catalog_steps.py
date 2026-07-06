"""Tests for step-trace persistence (catalog.steps + loop.steps_to_traces)."""

from mrx.pipeline import catalog
from mrx.pipeline import loop
from mrx.pipeline.loop import StepRecord


def _trace(**overrides):
    defaults = dict(
        id=catalog.new_step_id(),
        turn_id="turn_x",
        conversation_id="conv_x",
        step_num=1,
        action="fetch",
        reasoning="need by-desk data",
        fetch_query="FX Vega by desk",
        fetched_label="FX Vega by desk",
        reused_dataset_id="",
        capped=False,
    )
    defaults.update(overrides)
    return catalog.StepTrace(**defaults)


def test_save_and_list_steps_round_trips_in_step_order():
    catalog.save_steps([
        _trace(step_num=2, action="answer", reasoning="enough", fetch_query="",
               fetched_label="", capped=False),
        _trace(step_num=1),
    ])

    steps = catalog.list_steps(turn_id="turn_x")

    assert [s.step_num for s in steps] == [1, 2]  # ordered by step_num asc
    assert steps[0].action == "fetch"
    assert steps[1].action == "answer"


def test_capped_flag_round_trips_as_a_real_bool():
    catalog.save_steps([_trace(capped=True)])

    step = catalog.list_steps(turn_id="turn_x")[0]

    assert step.capped is True


def test_list_steps_is_scoped_to_the_turn():
    catalog.save_steps([_trace(turn_id="turn_a", reasoning="a")])
    catalog.save_steps([_trace(turn_id="turn_b", reasoning="b")])

    assert len(catalog.list_steps(turn_id="turn_a")) == 1
    assert catalog.list_steps(turn_id="turn_a")[0].reasoning == "a"


def test_save_steps_is_a_noop_for_an_empty_trace():
    # A turn with no steps: saving an empty list must not error and must
    # write nothing.
    catalog.save_steps([])
    assert catalog.list_steps(turn_id="anything") == []


def test_steps_to_traces_maps_records_and_defaults_none_to_empty_string():
    records = [
        StepRecord(step_num=1, action="fetch", reasoning="r1", fetch_query="q1",
                   fetched_label="by desk", reused_dataset_id=None, capped=False),
        StepRecord(step_num=2, action="answer", reasoning="done"),
    ]

    traces = loop.steps_to_traces(records, turn_id="turn_z", conversation_id="conv_z")

    assert all(t.turn_id == "turn_z" for t in traces)
    assert traces[0].reused_dataset_id == ""      # None -> "" for the NOT NULL column
    assert traces[1].fetch_query == ""            # answer step has no fetch query
    assert traces[1].fetched_label == ""
    assert [t.action for t in traces] == ["fetch", "answer"]


def test_steps_to_traces_output_persists_cleanly():
    # End-to-end: the conversion output must be directly saveable.
    records = [
        StepRecord(step_num=1, action="fetch", reasoning="r", fetch_query="q",
                   fetched_label="v", reused_dataset_id="ds_1", capped=False),
    ]
    traces = loop.steps_to_traces(records, turn_id="turn_p", conversation_id="conv_p")

    catalog.save_steps(traces)
    loaded = catalog.list_steps(turn_id="turn_p")

    assert len(loaded) == 1
    assert loaded[0].reused_dataset_id == "ds_1"
