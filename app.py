"""Streamlit frontend over the MRX pipeline (the controller loop).

Run with: streamlit run app.py

Presentation only — session/conversation identity, the sidebar, chat-history
rendering, the status box, and the per-step "investigation trace" panel. The
validation-gated core lives once in mrx/pipeline and is imported, never
duplicated here. See main.py for the CLI frontend.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from mrx.pipeline import catalog, connect_llm, fetch
from mrx.pipeline.errors_display import describe_error
from mrx.pipeline.number_display import format_number, format_numeric_columns
from mrx.pipeline.pipeline_errors import PipelineError
from mrx.pipeline import loop

st.set_page_config(page_title="MRX Link", page_icon="◆", layout="wide")


def _session_id() -> str:
    # session_id (per-tab, resets on refresh) and conversation_id (durable,
    # kept in the URL) are deliberately different ids — see catalog.py's
    # module docstring.
    ctx = get_script_run_ctx()
    return ctx.session_id if ctx else fetch.DEFAULT_SESSION_ID


def _conversation_id() -> str:
    existing = st.query_params.get("c")
    if existing:
        return existing
    new_id = catalog.new_conversation_id()
    st.query_params["c"] = new_id
    return new_id


st.title("◆ MRX Link")
st.caption("Ask a market-risk question — the agent fetches, looks, and decides its next step.")


@st.cache_resource
def get_llm():
    return connect_llm.get_llm(model="gpt55", version="2024-06-01")


EXAMPLE_QUESTIONS = [
    "Analyse the variation of FX Vega on GFXOPEMK over the last month.",
    "Which desk drove the biggest IR Delta change on IRUS this week, and which deals within it?",
    "Plot the FX Vega evolution of USDJPY under GFXOPEMK for June 2026.",
]

# The loop emits "decide:N" (a per-step decision) and per-step
# "plan:N"/"fetch:N"/"reuse:N" from fetch.get_view, plus a final "answer".
# Anything unrecognized falls back to a title-cased form (see _stage_label).
STAGE_LABELS = {
    "answer": "Computing the answer...",
}


def _stage_label(stage: str) -> str:
    if stage in STAGE_LABELS:
        return STAGE_LABELS[stage]
    if stage.startswith("decide:"):
        return f"Deciding the next step (step {stage.split(':', 1)[1]})..."
    if stage.startswith("plan:"):
        return "Building the MRX plan..."
    if stage.startswith("reuse:"):
        return "Reusing previously-fetched data..."
    if stage.startswith("fetch:"):
        return "Fetching data from MRX..."
    return stage.replace("_", " ").replace(":", ": ").capitalize() + "..."


def _value_preview(answer) -> str:
    if answer.type == "dataframe":
        return f"table with shape {answer.value.shape}"
    if answer.type == "chart":
        return "chart"
    if answer.type == "composed":
        # The narrative (fully replayable) is saved separately as the turn's
        # narration; this preview just notes the extra artifacts, which — like a
        # chart/table — aren't replayed from SQLite on reload.
        bits = [b for b, present in
                (("table", answer.value.get("table") is not None),
                 ("chart", answer.value.get("chart") is not None)) if present]
        return "analysis with " + " + ".join(bits) if bits else "analysis"
    return format_number(answer.value)


def _render_step_trace(steps):
    """The investigation trace — the headline audit view: every decision the
    loop made, in order, and why. This is the "how was this computed" that
    matters for a bank's risk system: not just the final data, but the reasoning
    chain that selected each fetch.
    """
    with st.expander(f"🔍 Investigation trace ({len(steps)} steps)", expanded=False):
        for step in steps:
            if step.action == "analyze":
                st.markdown(f"**Step {step.step_num} — Analyze the data.** {step.reasoning}")
            elif step.action == "respond":
                st.markdown(f"**Step {step.step_num} — Answer directly (no data needed).** {step.reasoning}")
            elif step.action == "answer":
                # Legacy trace rows from before the analyze/respond split.
                st.markdown(f"**Step {step.step_num} — Answer.** {step.reasoning}")
            elif getattr(step, "capped", False):
                st.markdown(
                    f"**Step {step.step_num} — Fetch refused (fetch limit reached).** "
                    f"The agent wanted: _{step.fetch_query}_ — {step.reasoning}"
                )
            else:
                source = "reused cached data" if step.reused_dataset_id else "fetched from MRX"
                label = step.fetched_label or step.fetch_query
                st.markdown(
                    f"**Step {step.step_num} — Fetch ({source}).** {label}\n\n"
                    f"_Why:_ {step.reasoning}"
                )


def _render_live_answer(result):
    """Render a just-computed answer. The ANSWER is the hero: it renders first,
    with room to breathe; the trace and source data are quiet, collapsed
    drill-downs below a divider.
    """
    answer = result.answer

    if answer.type == "composed":
        # A composed analytical answer: narrative, then chart, then table.
        st.markdown(answer.value["narrative"])
        if answer.value.get("chart") is not None:
            st.pyplot(answer.value["chart"])
        if answer.value.get("table") is not None:
            st.dataframe(_display_frame(answer.value["table"]), width='stretch')
    elif answer.type == "chart":
        st.markdown(answer.narration)
        st.pyplot(answer.value)
    elif answer.type == "dataframe":
        st.markdown(answer.narration)
        st.dataframe(_display_frame(answer.value), width='stretch')
    elif answer.type == "number":
        # A number is the one case a metric is right for — a short scalar.
        st.metric(label=answer.narration or "Result", value=format_number(answer.value))
    else:  # string / anything else — prose, never a metric.
        st.markdown(answer.narration)

    st.divider()
    _render_step_trace(result.steps)
    _render_data_and_method(result)


# Cap how much of a wide MRX frame we splash into the chat. Raw multirow frames
# can be 60+ columns (USDEUR, USDEUR (prv), USDEUR (diff), ... per pair) and
# hundreds of rows — dumping them whole overflows the page and buries the
# answer. Analysts who want the full frame open the debug harness; the UI just
# needs a readable preview.
_MAX_PREVIEW_ROWS = 20
_MAX_PREVIEW_COLS = 12


def _display_frame(df):
    """A readable preview of a (possibly very wide/long) dataframe for the chat:
    numeric columns formatted, capped to a sane number of rows/cols."""
    preview = df
    if preview.shape[1] > _MAX_PREVIEW_COLS:
        preview = preview.iloc[:, :_MAX_PREVIEW_COLS]
    if preview.shape[0] > _MAX_PREVIEW_ROWS:
        preview = preview.head(_MAX_PREVIEW_ROWS)
    return format_numeric_columns(preview)


def _render_data_and_method(result):
    """The 'Data gathered' and 'How was this computed?' expanders — shared by
    the composed and the single-result answer paths."""
    answer = result.answer
    if result.views:
        with st.expander(f"📊 Source data ({len(result.views)} view{'s' if len(result.views) != 1 else ''})"):
            for i, view in enumerate(result.views, start=1):
                reused_note = "reused" if view.reused_dataset_id else "fetched"
                st.markdown(f"**{i}. {view.plan.intent}**")
                st.caption(f"{reused_note} · {view.df.shape[0]} rows × {view.df.shape[1]} cols · {view.query}")
                st.dataframe(_display_frame(view.df), width='stretch')
                if view.df.shape[1] > _MAX_PREVIEW_COLS or view.df.shape[0] > _MAX_PREVIEW_ROWS:
                    st.caption(
                        f"Showing first {min(_MAX_PREVIEW_ROWS, view.df.shape[0])} rows × "
                        f"{min(_MAX_PREVIEW_COLS, view.df.shape[1])} cols of "
                        f"{view.df.shape[0]}×{view.df.shape[1]}."
                    )

    with st.expander("⚙️ How was this computed?"):
        if answer.method:
            st.markdown(f"**Method:** {answer.method}")
        st.markdown("**Code that was run:**")
        st.code(answer.code, language="python")


def _render_past_turn(turn: catalog.Turn):
    """Render a turn restored from the catalog; the step trace for a past turn
    is loaded separately and shown below.
    """
    if turn.answer_type == "number":
        st.metric(label=turn.narration or "Result", value=turn.value_preview)
    else:
        st.markdown(turn.narration)
        if turn.answer_type in ("dataframe", "chart", "composed"):
            st.caption(f"{turn.value_preview} — table/chart not replayed on reload; ask again to regenerate.")

    try:
        past_steps = catalog.list_steps(turn_id=turn.id)
    except Exception:
        past_steps = []
    if past_steps:
        st.divider()
        _render_step_trace(past_steps)

    with st.expander("⚙️ How was this computed?"):
        if turn.method:
            st.markdown(f"**Method:** {turn.method}")
        st.markdown("**Code that was run:**")
        st.code(turn.code, language="python")


@dataclass
class _FailedTurn:
    question: str
    error_message: str
    url: str = ""  # the MRX link involved, when the failure was a fetch


def _render_error(error_message, url=""):
    """Show a failure, and — when it was a fetch failure — the exact MRX link
    that produced it, so the user can open it and diagnose (e.g. an MRX 500)."""
    st.error(error_message)
    if url:
        st.caption("MRX link that failed (open it to see MRX's own error):")
        st.code(url, language=None)
        st.markdown(f"[Open in MRX]({url})")


def _render_history_item(item):
    # Duck-typed, not isinstance: Streamlit redefines _FailedTurn on every
    # script rerun, so an instance stashed in session_state on one rerun fails
    # an isinstance() check on the next (isinstance compares class identity,
    # which doesn't survive a rerun; hasattr does).
    with st.chat_message("user"):
        st.markdown(item.question)
    with st.chat_message("assistant"):
        if hasattr(item, "error_message"):
            _render_error(item.error_message, getattr(item, "url", ""))
        else:
            _render_past_turn(item)


def _format_timestamp(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str).strftime("%b %d, %H:%M")
    except ValueError:
        return iso_str


with st.sidebar:
    if st.button("+ New chat", use_container_width=True, type="primary"):
        st.query_params.clear()
        st.session_state.pop("turns", None)
        st.rerun()

    st.divider()
    st.subheader("Conversations", anchor=False)

    active_conversation_id = st.query_params.get("c")
    try:
        conversations = catalog.list_conversations()
    except Exception:
        conversations = []

    if not conversations:
        st.caption("No conversations yet — ask a question to start one.")
    for summary in conversations:
        is_active = summary.conversation_id == active_conversation_id
        question_preview = summary.first_question
        if len(question_preview) > 45:
            question_preview = question_preview[:42] + "..."

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
        status_placeholder = st.empty()
        with status_placeholder.container():
            status = st.status("Starting the investigation...", expanded=True)
            stream_placeholder = status.empty()

        def _on_stage(stage):
            status.update(label=_stage_label(stage))
            if stage != "answer":
                stream_placeholder.empty()

        def _on_token(buffer):
            stream_placeholder.code(buffer, language="python")

        try:
            result = loop.run_agent_loop(
                get_llm(), query, on_stage=_on_stage, on_token=_on_token,
                session_id=_session_id(), conversation_id=conversation_id,
            )
        except PipelineError as e:
            status.update(label="Failed", state="error", expanded=True)
            error_message = describe_error(e)
            failed_url = getattr(e, "url", None) or ""
            _render_error(error_message, failed_url)
            st.session_state.turns.append(
                _FailedTurn(question=query, error_message=error_message, url=failed_url)
            )
        else:
            status_placeholder.empty()

            _render_live_answer(result)

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
            st.session_state.turns.append(new_turn)
            # Persist the turn AND its investigation trace (the audit chain).
            # Both writes are best-effort — a storage hiccup must not take
            # away the answer the user already has on screen.
            try:
                catalog.save_turn(new_turn)
                catalog.save_steps(
                    loop.steps_to_traces(
                        result.steps, turn_id=new_turn.id, conversation_id=conversation_id
                    )
                )
            except Exception:
                pass
