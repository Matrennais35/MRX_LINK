"""Tests for user-feedback capture (mrx.pipeline.feedback)."""

import json

from mrx_analyst.storage import feedback
from dataclasses import dataclass


@dataclass
class AnalysisPlan:  # M3 stub — feedback duck-types the four fields
    target: str
    approach: str
    representation: str
    success_criteria: str


def test_feedback_writes_jsonl_and_readable_files_with_the_plan(tmp_catalog):
    plan = AnalysisPlan(
        target="which book drove it", approach="by book then deal",
        representation="waterfall", success_criteria="names the dominant driver",
    )
    feedback.record_feedback(
        turn_id="turn_1", conversation_id="conv_1",
        question="what drove the increase?", plan=plan,
        rating="down", comment="misread the question — I meant by desk",
        created_at="2026-07-06T12:00:00+00:00",
    )

    jsonl_path = tmp_catalog.CATALOG_DIR / "feedback.jsonl"
    txt_path = tmp_catalog.CATALOG_DIR / "feedback.txt"

    # JSONL: one machine-readable record with the plan captured alongside.
    record = json.loads(jsonl_path.read_text().strip())
    assert record["question"] == "what drove the increase?"
    assert record["rating"] == "down"
    assert record["comment"] == "misread the question — I meant by desk"
    assert record["plan"]["target"] == "which book drove it"
    assert record["plan"]["representation"] == "waterfall"

    # TXT: human-readable, self-contained block with question + plan + verdict.
    text = txt_path.read_text()
    assert "what drove the increase?" in text
    assert "which book drove it" in text  # the plan's target
    assert "👎 bad" in text
    assert "misread the question" in text


def test_feedback_appends_multiple_records(tmp_catalog):
    for i in range(3):
        feedback.record_feedback(
            turn_id=f"turn_{i}", conversation_id="conv_1", question=f"q{i}",
            plan=None, rating="up", comment="", created_at="2026-07-06T12:00:00+00:00",
        )
    lines = (tmp_catalog.CATALOG_DIR / "feedback.jsonl").read_text().strip().splitlines()
    assert len(lines) == 3


def test_list_feedback_returns_records_most_recent_first(tmp_catalog):
    for i in range(3):
        feedback.record_feedback(
            turn_id=f"turn_{i}", conversation_id="conv_1", question=f"q{i}",
            plan=None, rating="up", comment="", created_at=f"2026-07-0{i+1}T12:00:00+00:00",
        )
    records = feedback.list_feedback()
    assert len(records) == 3
    assert records[0]["question"] == "q2"  # most recent first
    assert records[-1]["question"] == "q0"


def test_list_feedback_empty_when_none(tmp_catalog):
    assert feedback.list_feedback() == []
    assert feedback.readable_text() == ""


def test_feedback_handles_no_plan_gracefully(tmp_catalog):
    # A trivial-path answer has no plan; feedback must still record cleanly.
    feedback.record_feedback(
        turn_id="turn_x", conversation_id="conv_1", question="hi",
        plan=None, rating="", comment="just testing",
        created_at="2026-07-06T12:00:00+00:00",
    )
    record = json.loads((tmp_catalog.CATALOG_DIR / "feedback.jsonl").read_text().strip())
    assert record["plan"] is None
    assert "(none — trivial path" in (tmp_catalog.CATALOG_DIR / "feedback.txt").read_text()
