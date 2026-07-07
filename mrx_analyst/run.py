"""run_question — the vision's composition, readable top to bottom:

    DESIGN   the Answer Blueprint (intent + menu + gold standard)
    EXECUTE  the tool loop fills it (gated fetches, free-code analysis)
    WRITE    the desk note, assembled from the note + section artifacts

Critic joins in P5. Persistence (turn, trace, chart PNGs) happens here so
headless runs persist identically to the app.
"""

import io
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from .common.answer import Answer
from .common.events import EventKind, no_emit
from .core.context import FetchBudget
from .design import designer
from .execute import loop
from .execute.session import ToolSession
from .mrx import profiler
from .mrx.registry import DEFAULT_VIEW
from .storage import catalog
from .write import writer

# Per-role effort tiers (proven in the pipeline: high everywhere is too slow).
# The LOOP uses the "tools" tier — a client built WITHOUT reasoning_effort:
# Azure rejects function tools + reasoning_effort on chat/completions (live
# 400); structured-output roles keep their effort tiers.
ROLE_EFFORT = {"designer": "high", "loop": "tools", "url": "medium", "critic": "low"}


def _llm_for(llm, role: str):
    if not isinstance(llm, dict):
        return llm
    effort = ROLE_EFFORT.get(role, "medium")
    return llm.get(effort) or llm.get("medium") or llm.get("high") or next(iter(llm.values()))


@dataclass
class RunResult:
    answer: Answer
    blueprint: object
    session: ToolSession
    turn_id: str
    timings: Dict[str, float] = field(default_factory=dict)   # seconds per phase


def run_question(
    llm,
    question: str,
    *,
    session_id: str,
    conversation_id: Optional[str] = None,
    emit=no_emit,
    max_fetches: Optional[int] = None,
    view=None,
) -> RunResult:
    view = view if view is not None else DEFAULT_VIEW
    timings: Dict[str, float] = {}

    session = ToolSession(session_id=session_id, conversation_id=conversation_id, emit=emit)
    if max_fetches is not None:
        session.budget = FetchBudget(max_fetches=max_fetches)
    session.install_namespace()

    history = _load_history(session)

    # ---- DESIGN ---------------------------------------------------------------
    emit(EventKind.STATUS, {"label": "Designing the answer…"})
    t0 = time.monotonic()
    blueprint = designer.design(
        _llm_for(llm, "designer"), question,
        history=history, available_data=_available_data_text(session),
    )
    timings["design"] = time.monotonic() - t0
    emit(EventKind.AGENT, {"role": "designer", "output": blueprint.model_dump()})

    if blueprint.clarification:
        answer = Answer(narrative=blueprint.clarification)
        turn_id = _persist(session, question, answer)
        return RunResult(answer=answer, blueprint=blueprint, session=session,
                         turn_id=turn_id, timings=timings)

    # ---- EXECUTE ---------------------------------------------------------------
    emit(EventKind.STATUS, {"label": "Executing the blueprint…"})
    t0 = time.monotonic()
    note_markdown = loop.run_loop(
        _llm_for(llm, "loop"), _llm_for(llm, "url"), view, session, blueprint, question,
    )
    timings["execute"] = time.monotonic() - t0

    # ---- WRITE -----------------------------------------------------------------
    t0 = time.monotonic()
    answer = writer.assemble(note_markdown, blueprint, session)
    timings["write"] = time.monotonic() - t0

    turn_id = _persist(session, question, answer)
    return RunResult(answer=answer, blueprint=blueprint, session=session,
                     turn_id=turn_id, timings=timings)


# ---- context + persistence (proven catalog machinery, reused) -----------------

def _load_history(session: ToolSession) -> list:
    """Prior turns + this conversation's cached datasets seeded as zero-cost
    evidence AND into the python namespace. Degrades to empty on any error."""
    if not session.conversation_id:
        return []
    try:
        history = catalog.list_turns(conversation_id=session.conversation_id)
    except Exception:
        history = []
    try:
        from .core.context import Evidence
        from .tools.mrx_fetch import _unique_label
        for dataset in catalog.list_for_conversation(conversation_id=session.conversation_id):
            try:
                df = catalog.load_df(dataset.id)
            except Exception:
                continue
            if df is None:
                continue
            label = _unique_label(dataset.description, session)
            session.evidence.append(Evidence(
                dataset_id=dataset.id, label=label, plan=dataset.plan,
                df=df, profile=profiler.profile(df), provenance="reused",
            ))
            session.register_frame(label, df)
    except Exception:
        pass
    return history


def _available_data_text(session: ToolSession) -> str:
    return "\n\n".join(
        f"[{e.label}]\n{e.profile.render_text()}" for e in session.evidence
    )


def _persist(session: ToolSession, question: str, answer: Answer) -> str:
    turn_id = catalog.new_turn_id()
    try:
        catalog.save_turn(catalog.Turn(
            id=turn_id,
            conversation_id=session.conversation_id or session.session_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            question=question,
            narration=answer.narrative,
            method="; ".join(f"code x{len(session.code_log)}" for _ in [0] if session.code_log),
            answer_type="answer",
            value_preview=f"report with {len(answer.sections)} sections" if answer.sections else "prose",
            code="\n\n# ---\n\n".join(session.code_log),
        ))
        catalog.save_steps(session.trace, turn_id=turn_id,
                           conversation_id=session.conversation_id or session.session_id)
        for i, fig in enumerate(answer.charts):
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
            catalog.save_turn_image(turn_id, buf.getvalue(), index=i)
    except Exception:
        pass  # storage hiccups must never take away an answer
    return turn_id
