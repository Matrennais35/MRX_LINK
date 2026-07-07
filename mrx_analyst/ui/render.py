"""Rendering the ONE Answer shape + the run's reasoning artifacts.

The answer is the hero: narrative first (with $-escaping — Streamlit treats
$...$ as LaTeX and garbles money amounts), then whichever parts exist (chart at
a controlled size, table as a capped preview, value as a metric). Below a
divider: the plan (how the assistant approached it), the trace (every agent
decision / tool run / gate), the evidence, and the feedback form. One branch
point — parts-present — instead of the old 5-way type union.
"""

from datetime import datetime, timezone

import streamlit as st

from ..storage import catalog, feedback
from .format import format_number, format_numeric_columns

# Cap what a wide MRX frame splashes into the chat — the full frame is always
# in the trace/debug harness; the UI needs a readable preview.
_MAX_PREVIEW_ROWS = 20
_MAX_PREVIEW_COLS = 12


def prose(text: str) -> None:
    """Markdown with literal $ escaped (LaTeX-garbling fix, proven in the old app)."""
    st.markdown((text or "").replace("$", "\\$"))


def _display_frame(df):
    preview = df
    if preview.shape[1] > _MAX_PREVIEW_COLS:
        preview = preview.iloc[:, :_MAX_PREVIEW_COLS]
    if preview.shape[0] > _MAX_PREVIEW_ROWS:
        preview = preview.head(_MAX_PREVIEW_ROWS)
    return format_numeric_columns(preview)


def _chart(fig) -> None:
    """Controlled-size chart — a conversation figure, not a poster."""
    fig.set_size_inches(7, 3.6)
    fig.set_dpi(100)
    col, _ = st.columns([3, 1])
    with col:
        st.pyplot(fig, use_container_width=True)


def render_answer(answer) -> None:
    """Narrative (the executive summary) always; then the report SECTIONS in
    outline order when the analysis earned them, else the simple parts. An
    unfilled section renders its reason — a visible gap, never silence."""
    prose(answer.narrative)
    if answer.sections:
        for section in answer.sections:
            st.markdown(f"#### {section.title}")
            if section.status == "unfilled":
                st.caption(f"⚠ {section.reason}")
                continue
            if section.text:
                prose(section.text)
            if section.chart is not None:
                _chart(section.chart)
            if section.table is not None:
                if getattr(section, "full_table", False):
                    # Extraction mode: completeness IS the answer — every row.
                    st.dataframe(format_numeric_columns(section.table), width="stretch")
                else:
                    st.dataframe(_display_frame(section.table), width="stretch")
                    if (section.table.shape[0] > _MAX_PREVIEW_ROWS
                            or section.table.shape[1] > _MAX_PREVIEW_COLS):
                        st.caption(f"Showing a preview of {section.table.shape[0]}x{section.table.shape[1]}.")
        return
    if answer.value is not None:
        st.metric(label="Result", value=answer.value)
    if answer.chart is not None:
        _chart(answer.chart)
    if answer.table is not None:
        st.dataframe(_display_frame(answer.table), width="stretch")
        if answer.table.shape[0] > _MAX_PREVIEW_ROWS or answer.table.shape[1] > _MAX_PREVIEW_COLS:
            st.caption(f"Showing a preview of {answer.table.shape[0]}x{answer.table.shape[1]}.")


def render_blueprint(blueprint) -> None:
    """The Designer's up-front contract — the pivotal step, reviewable.
    Collapsed by default (the answer is the hero)."""
    if blueprint is None:
        return
    with st.expander("🧠 The blueprint (how the answer was designed)", expanded=False):
        prose(f"**Target** — {blueprint.target}")
        for assumption in getattr(blueprint, "assumptions", []):
            st.caption(f"assumed: {assumption}")
        for i, sec in enumerate(getattr(blueprint, "sections", []), 1):
            prose(f"**{i}. {sec.title}** — {sec.must_establish}  \n"
                  f"*data:* {sec.data_needed} · *shown as:* {sec.artifact}")
        for f in getattr(blueprint, "fetches", []):
            st.caption(f"fetch ({f.when}): {f.request}")


_KIND_ICONS = {"agent": "🧠", "tool": "🔧", "gate": "🛡"}


def render_trace(steps) -> None:
    """The audit trace — works for both live Step objects and persisted
    StepTrace rows (same field names by construction)."""
    if not steps:
        return
    with st.expander(f"🔍 Trace ({len(steps)} steps)", expanded=False):
        for i, step in enumerate(steps, start=1):
            icon = _KIND_ICONS.get(step.kind, "•")
            flag = "" if step.status == "ok" else f"  **[{step.status.upper()}]**"
            st.markdown(f"{icon} **{i}. {step.name}**{flag} — {step.summary}")


def render_evidence(evidence) -> None:
    if not evidence:
        return
    with st.expander(f"📊 Source data ({len(evidence)} dataset{'s' if len(evidence) != 1 else ''})"):
        for e in evidence:
            tag = {"fetched": "fetched", "reused": "reused", "computed": "computed"}.get(e.provenance, "")
            st.markdown(f"**{e.label}** ({tag})")
            st.caption(e.profile.render_text().splitlines()[0])
            st.dataframe(_display_frame(e.df), width="stretch")
            if e.plan is not None:
                st.caption(f"MRX URL: `{e.plan.url}`")


def render_error(message: str, url: str = "") -> None:
    st.error(message)
    if url:
        st.caption("MRX link that failed (open it to see MRX's own error):")
        st.code(url, language=None)
        st.markdown(f"[Open in MRX]({url})")


def render_feedback_form(turn_id: str, conversation_id: str, question: str, plan) -> None:
    """Rating + comment per answer, written next to the plan it judges (the
    plain-file capture the reviewer reads). Skipped once submitted."""
    submitted = st.session_state.setdefault("feedback_done", set())
    if turn_id in submitted:
        st.caption("✓ Thanks — feedback recorded.")
        return
    with st.expander("💬 Was this answer useful? (feedback)", expanded=False):
        rating = st.radio("Rating", options=["👍 good", "👎 bad", "no rating"], horizontal=True,
                          index=2, key=f"fb_rating_{turn_id}", label_visibility="collapsed")
        comment = st.text_area(
            "What worked, or what was wrong / what you actually meant?",
            key=f"fb_comment_{turn_id}",
            placeholder="e.g. right data but it misread the question — I wanted it by desk",
        )
        if st.button("Submit feedback", key=f"fb_submit_{turn_id}"):
            try:
                feedback.record_feedback(
                    turn_id=turn_id, conversation_id=conversation_id, question=question,
                    plan=plan, rating={"👍 good": "up", "👎 bad": "down", "no rating": ""}[rating],
                    comment=comment, created_at=datetime.now(timezone.utc).isoformat(),
                )
                submitted.add(turn_id)
                st.rerun()
            except Exception:
                st.warning("Could not save feedback — please try again.")


def render_past_turn(turn) -> None:
    """A turn restored from the catalog, rendered with FULL fidelity — the
    same sections/tables/charts as the live turn (a follow-up's rerun must
    not degrade earlier answers). Turns predating the answer store fall back
    to narration + chart PNGs."""
    try:
        images = catalog.load_turn_images(turn.id)
    except Exception:
        images = []
    try:
        stored = catalog.load_turn_answer(turn.id)
    except Exception:
        stored = None

    if stored is not None:
        prose(stored["narrative"])
        # Mirrors render_answer exactly — replay must be indistinguishable
        # from the live turn (heading level, gap style, chart-then-table).
        for entry in stored["sections"]:
            st.markdown(f"#### {entry['title']}")
            if entry["status"] != "filled":
                st.caption(f"⚠ {entry['reason']}")
                continue
            if entry["text"]:
                prose(entry["text"])
            idx = entry["chart_index"]
            if idx is not None and idx < len(images):
                col, _ = st.columns([3, 1])
                with col:
                    st.image(images[idx])
            if entry["table"] is not None:
                if entry.get("full_table"):
                    st.dataframe(format_numeric_columns(entry["table"]), width="stretch")
                else:
                    st.dataframe(_display_frame(entry["table"]), width="stretch")
    else:
        prose(turn.narration)
        for image in images:
            col, _ = st.columns([3, 1])
            with col:
                st.image(image)
    try:
        steps = catalog.list_steps(turn_id=turn.id)
    except Exception:
        steps = []
    render_trace(steps)
