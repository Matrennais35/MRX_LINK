"""User feedback capture — the one signal you can't get from tests: did the
answer actually serve what the user meant?

Each answer's feedback is written alongside the LLM's OWN reasoning (the
question, the analysis plan, the rating, the comment) so a reviewer can read
(what was asked -> how it reasoned -> whether it worked -> why) in one block and
diagnose WHERE it went wrong (wrong target? right target, wrong breakdown? bad
synthesis?).

Written to two files in the catalog dir so they're easy to grab and share:
- feedback.jsonl : one JSON object per line (machine-readable, for later analysis)
- feedback.txt   : the same records, human-readable (paste-and-review)

Deliberately plain files, not a SQLite table: the whole point is that you can
pull `feedback.txt` off the machine running the app and hand it over for review.
"""

import json
from pathlib import Path

from . import catalog


def _paths():
    """Resolve the feedback file paths at CALL time from catalog.CATALOG_DIR, so
    tests that monkeypatch the catalog dir (see conftest.tmp_catalog) redirect
    these too — same late-binding the catalog's own storage uses."""
    base = catalog.CATALOG_DIR
    return base / "feedback.jsonl", base / "feedback.txt"


def _plan_dict(plan):
    """The plan's fields as a plain dict (or None) — plan is an AnalysisPlan or
    None. Kept defensive: any object with the four fields works, and anything
    else degrades to None rather than raising."""
    if plan is None:
        return None
    try:
        return {
            "target": plan.target,
            "approach": plan.approach,
            "representation": plan.representation,
            "success_criteria": plan.success_criteria,
        }
    except AttributeError:
        return None


def record_feedback(*, turn_id, conversation_id, question, plan, rating, comment, created_at):
    """Append one feedback record to feedback.jsonl and feedback.txt.

    `rating` is "up" | "down" | "" (no rating), `comment` is free text. `plan`
    is the AnalysisPlan the orchestrator reasoned (or None). `created_at` is an
    ISO timestamp passed in by the caller (the app has it; this module doesn't
    reach for the clock itself).
    """
    catalog.CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path, txt_path = _paths()

    record = {
        "turn_id": turn_id,
        "conversation_id": conversation_id,
        "created_at": created_at,
        "question": question,
        "plan": _plan_dict(plan),
        "rating": rating,
        "comment": comment,
    }

    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    with txt_path.open("a", encoding="utf-8") as f:
        f.write(_format_readable(record))


def _format_readable(record) -> str:
    """One self-contained, readable block per feedback record — question, the
    LLM's plan, and the user's verdict together, so a reviewer sees the whole
    (asked -> reasoned -> worked?) picture without cross-referencing anything."""
    rating_label = {"up": "👍 good", "down": "👎 bad", "": "(no rating)"}.get(record["rating"], record["rating"])
    lines = [
        "=" * 78,
        f"[{record['created_at']}]  turn {record['turn_id']}",
        f"QUESTION: {record['question']}",
    ]
    plan = record["plan"]
    if plan:
        lines += [
            "PLAN:",
            f"  target        : {plan['target']}",
            f"  approach      : {plan['approach']}",
            f"  representation: {plan['representation']}",
            f"  success       : {plan['success_criteria']}",
        ]
    else:
        lines.append("PLAN: (none — trivial path or planning skipped)")
    lines += [
        f"RATING: {rating_label}",
        f"COMMENT: {record['comment'] or '(none)'}",
        "",
    ]
    return "\n".join(lines)
