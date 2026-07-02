"""Streamlit frontend over the mrx pipeline. See main.py for the CLI frontend.

Run with: streamlit run app.py
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from mrx.pipeline import catalog, connect_llm, orchestrator
from mrx.pipeline.errors_display import describe_error
from mrx.pipeline.number_display import format_number, format_numeric_columns
from mrx.pipeline.pipeline_errors import PipelineError

st.set_page_config(page_title="MRX Link", page_icon="◆", layout="wide")

# No custom CSS: the dark background, accent color, and font all come from
# .streamlit/config.toml's [theme] section, which every native widget below
# (st.title, st.metric, st.container(border=True), etc.) already respects.
# Hand-rolled unsafe_allow_html divs are gone in favor of those widgets —
# less to maintain, and it stays visually consistent with Streamlit's own
# spacing/contrast choices instead of fighting them.


def _session_id() -> str:
    # Ties dataset-reuse scoping (mrx/pipeline/catalog.py) to this actual
    # browser session, rather than every user sharing
    # orchestrator.DEFAULT_SESSION_ID — without this, "prefer this
    # conversation's own recent fetches" never runs, every reuse candidate
    # is just ranked by recency across all users.
    #
    # This is deliberately NOT the same identifier as conversation_id
    # below: session_id resets on every page refresh/new tab (fine for
    # dataset-reuse — a missed reuse just costs one extra fetch), but
    # conversation history must survive a refresh, so it needs an
    # identifier that doesn't reset. See catalog.py's module docstring.
    ctx = get_script_run_ctx()
    return ctx.session_id if ctx else orchestrator.DEFAULT_SESSION_ID


def _conversation_id() -> str:
    # A durable id kept in the URL's query params (not st.session_state,
    # which is wiped on refresh) so reloading the page or reopening a
    # bookmarked/shared URL reconnects to the same conversation history —
    # this is the actual fix for "I can't continue a conversation, don't
    # see saved history": conversations are stored in the catalog (see
    # catalog.save_turn/list_turns), keyed by this id, not by session_id.
    existing = st.query_params.get("c")
    if existing:
        return existing
    new_id = catalog.new_conversation_id()
    st.query_params["c"] = new_id
    return new_id


st.title("◆ MRX Link")
st.caption("Ask a market-risk question in plain English.")


@st.cache_resource
def get_llm():
    return connect_llm.get_llm(model="gpt55", version="2024-06-01")


EXAMPLE_QUESTIONS = [
    "What is the average EQ PV Diff between 2026-05-30 and 2026-06-03 for US_SPX in GLEQD?",
    "Show IR Delta on IRUS by product for COB today, compared with T-1.",
    "Plot the FX Vega evolution of USDJPY under GFXOPEMK for June 2026.",
]

STAGE_LABELS = {
    "plan": "Building the MRX plan...",
    "reuse": "Reusing previously-fetched data...",
    "fetch": "Fetching data from MRX...",
    "answer": "Computing the answer...",
}


def _stage_label(stage: str) -> str:
    # Falls back to a generic label instead of KeyError-ing for any stage
    # name not in STAGE_LABELS above — e.g. a per-view "fetch:by-desk"
    # during a multi-fetch question. Title-cases the raw stage name so an
    # unanticipated stage still reads as something sensible, not "??? ".
    if stage in STAGE_LABELS:
        return STAGE_LABELS[stage]
    return stage.replace("_", " ").replace(":", ": ").capitalize() + "..."


def _value_preview(answer) -> str:
    # What gets durably stored for a turn's answer. "number"/"string"
    # results are small and fully replayable, so the actual value is kept
    # verbatim. "dataframe"/"chart" results are NOT replayed on reopen (a
    # matplotlib Figure isn't storable in SQLite, and a full dataframe can
    # be arbitrarily large) — a short note is stored instead, and the
    # narration text (always saved separately) still describes what it
    # showed. See catalog.Turn's docstring for the same tradeoff.
    if answer.type == "dataframe":
        return f"table with shape {answer.value.shape}"
    if answer.type == "chart":
        return "chart"
    return format_number(answer.value)


def _render_live_answer(answer, result):
    """Render a just-computed answer with its full interactive value
    (chart/dataframe/metric) — used only for the turn from THIS run, never
    for turns restored from history (see _render_past_turn).
    """
    st.write(answer.narration)

    if answer.type == "chart":
        st.pyplot(answer.value)
    elif answer.type == "dataframe":
        st.dataframe(format_numeric_columns(answer.value))
    else:
        st.metric("Computed value", format_number(answer.value))

    if result.attempts > 1:
        st.caption(f"Took {result.attempts} attempts to build a valid MRX plan.")

    if result.views:
        with st.expander(f"Views used ({len(result.views)})"):
            # This question needed several MRX fetches at once — show
            # what each one was, not just the first (result.plan/df
            # below only ever reflect the first view for a multi-view
            # answer, since PipelineResult keeps one "primary" view for
            # backward compatibility with the single-view case).
            for i, view in enumerate(result.views, start=1):
                reused_note = " (reused)" if view.reused_dataset_id else " (fetched)"
                st.markdown(f"**{i}. {view.plan.intent}**{reused_note}")
                st.caption(f"Query: {view.query}")
                st.dataframe(format_numeric_columns(view.df))

    with st.expander("How was this computed?"):
        if answer.method:
            st.markdown(f"**Method:** {answer.method}")
        st.markdown("**Code that was run:**")
        st.code(answer.code, language="python")
        if not result.views:
            st.markdown("**Source data (from MRX):**")
            st.dataframe(format_numeric_columns(result.df))

    with st.expander("Plan details"):
        st.markdown(f"**Intent:** {result.plan.intent}")
        st.markdown(f"**Reasoning:** {result.plan.view_reasoning}")
        if result.plan.assumptions:
            st.markdown("**Assumptions:**")
            for assumption in result.plan.assumptions:
                st.markdown(f"- {assumption}")
        st.markdown(f"**Confidence:** {result.plan.confidence:.2f}")
        st.markdown(f"**MRX URL:** `{result.plan.url}`")


def _render_past_turn(turn: catalog.Turn):
    """Render a turn restored from the catalog (a prior page load/session).
    Only narration + method + code are available — see _value_preview and
    catalog.Turn's docstring for why the chart/table itself isn't replayed.
    """
    st.write(turn.narration)
    if turn.answer_type == "number":
        st.metric("Computed value", turn.value_preview)
    elif turn.answer_type in ("dataframe", "chart"):
        st.caption(f"{turn.value_preview} — not replayed on reload; ask again to regenerate.")

    with st.expander("How was this computed?"):
        if turn.method:
            st.markdown(f"**Method:** {turn.method}")
        st.markdown("**Code that was run:**")
        st.code(turn.code, language="python")


@dataclass
class _FailedTurn:
    """A question that errored out, kept in st.session_state (NOT the
    catalog — a failure isn't an answer worth surviving a refresh) purely
    so it doesn't visibly appear and then silently vanish from the thread
    the next time the script reruns (e.g. on the next question).
    """
    question: str
    error_message: str


def _render_history_item(item):
    # Duck-typed, NOT isinstance(item, _FailedTurn) — Streamlit re-executes
    # this whole script's source on every rerun, which redefines _FailedTurn
    # as a genuinely new class object each time. An instance stashed in
    # st.session_state on one rerun and checked with isinstance() on the
    # NEXT rerun fails that check even though it's structurally the same
    # kind of object — isinstance compares class identity, not shape, and
    # that identity doesn't survive a rerun. hasattr does.
    with st.chat_message("user"):
        st.markdown(item.question)
    with st.chat_message("assistant"):
        if hasattr(item, "error_message"):
            st.error(item.error_message)
        else:
            _render_past_turn(item)


def _format_timestamp(iso_str: str) -> str:
    # A short, readable form for the sidebar ("Jul 02, 14:30") rather than
    # a raw ISO string — this is a display concern local to the sidebar,
    # not something number_display.py needs to own.
    try:
        return datetime.fromisoformat(iso_str).strftime("%b %d, %H:%M")
    except ValueError:
        return iso_str


with st.sidebar:
    if st.button("+ New chat", use_container_width=True, type="primary"):
        # Dropping the "c" query param makes the next _conversation_id()
        # call mint a fresh id — the old conversation stays in the catalog,
        # just no longer the active one for this tab.
        st.query_params.clear()
        st.session_state.pop("turns", None)
        st.rerun()

    st.divider()
    st.subheader("Conversations", anchor=False)

    active_conversation_id = st.query_params.get("c")
    try:
        conversations = catalog.list_conversations()
    except Exception:
        # Same "don't let a storage hiccup break the app" stance as
        # elsewhere — an empty list here just means no history shows up,
        # not a crash.
        conversations = []

    if not conversations:
        st.caption("No conversations yet — ask a question to start one.")
    for summary in conversations:
        is_active = summary.conversation_id == active_conversation_id
        question_preview = summary.first_question
        if len(question_preview) > 45:
            question_preview = question_preview[:42] + "..."

        # Each conversation gets its own bordered card, rather than a bare
        # button + caption stacked in the flow — groups the question,
        # activity summary, and click target into one visually distinct
        # unit, which reads much better in a narrow sidebar than plain
        # stacked text does.
        with st.container(border=True):
            st.markdown(f"{'🟢 ' if is_active else ''}**{question_preview}**")
            st.caption(
                f"{summary.turn_count} turn{'s' if summary.turn_count != 1 else ''} · "
                f"{_format_timestamp(summary.last_activity_at)}"
            )
            if not is_active:
                if st.button("Open", key=f"conv_{summary.conversation_id}", use_container_width=True):
                    st.query_params["c"] = summary.conversation_id
                    st.session_state.pop("turns", None)
                    st.rerun()

    st.divider()
    with st.expander("Recently fetched data"):
        try:
            recent_datasets = catalog.list_all(session_id=_session_id())[:10]
        except Exception:
            recent_datasets = []

        if not recent_datasets:
            st.caption("No datasets fetched yet.")
        for dataset in recent_datasets:
            st.markdown(f"**{dataset.description}**")
            st.caption(_format_timestamp(dataset.created_at))


conversation_id = _conversation_id()

if "turns" not in st.session_state:
    # First render of this conversation_id in this Python process — load
    # any turns already saved for it (e.g. the tab was refreshed, or a
    # bookmarked/shared URL was reopened). Subsequent reruns within the
    # same session reuse st.session_state instead of re-querying the
    # catalog on every keystroke/interaction.
    st.session_state.turns = catalog.list_turns(conversation_id=conversation_id)

for history_item in st.session_state.turns:
    _render_history_item(history_item)

if not st.session_state.turns:
    st.caption("Examples")
    example_cols = st.columns(len(EXAMPLE_QUESTIONS))
    clicked_example = None
    for col, example in zip(example_cols, EXAMPLE_QUESTIONS):
        if col.button(example, use_container_width=True):
            clicked_example = example
else:
    clicked_example = None

query = st.chat_input("Ask a market-risk question, or a follow-up...") or clicked_example

if query:
    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        status = st.status(STAGE_LABELS["plan"], expanded=True)
        stream_placeholder = status.empty()

        def _on_stage(stage):
            status.update(label=_stage_label(stage))
            if stage != "answer":
                stream_placeholder.empty()

        def _on_token(buffer):
            # Live view of the LLM writing pandas code / narrating the
            # result, during the "answer" stage — the two are visually
            # indistinguishable here (both are just raw streamed text),
            # which is honest: this is literally what the model is
            # emitting, not a curated summary of it. st.code (not
            # st.markdown) so it's monospaced and never needs manual
            # HTML-escaping of "<"/">"/"&" that streamed pandas code
            # routinely contains.
            stream_placeholder.code(buffer, language="python")

        try:
            result = orchestrator.run(
                get_llm(), query, on_stage=_on_stage, on_token=_on_token, session_id=_session_id(),
                allow_multi_fetch=True,
            )
        except PipelineError as e:
            status.update(label="Failed", state="error", expanded=True)
            error_message = describe_error(e)
            st.error(error_message)
            # Kept in session_state (not the catalog — a failure isn't an
            # answer worth surviving a refresh) so it stays visible in the
            # thread for the rest of this session instead of silently
            # vanishing the next time the script reruns (e.g. on the next
            # question) — see _FailedTurn's docstring.
            st.session_state.turns.append(_FailedTurn(question=query, error_message=error_message))
        else:
            stream_placeholder.empty()
            status.update(label="Done", state="complete", expanded=False)

            _render_live_answer(result.answer, result)

            new_turn = catalog.Turn(
                id=catalog.new_turn_id(),
                conversation_id=conversation_id,
                created_at=datetime.now(timezone.utc).isoformat(),
                question=query,
                narration=result.answer.narration,
                method=result.answer.method,
                answer_type=result.answer.type,
                value_preview=_value_preview(result.answer),
                code=result.answer.code,
            )
            # Kept in session_state regardless of whether the catalog write
            # succeeds — a storage hiccup (same stance as
            # orchestrator.py's _save_to_catalog) must not take away an
            # answer the user already has on screen, it just won't survive
            # a refresh if the write itself failed.
            st.session_state.turns.append(new_turn)
            try:
                catalog.save_turn(new_turn)
            except Exception:
                pass
