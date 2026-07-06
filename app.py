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
    if stage == "plan:analysis":
        return "Thinking about how to approach this…"
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


def _prose(text: str):
    """Render analyst prose as markdown, but ESCAPE literal '$' first. Streamlit
    treats '$...$' as LaTeX math, so a synthesis mentioning figures like "$1.79m"
    or "+4.29m ... -2.85m" gets rendered as squished italic math (spaces eaten,
    numbers garbled — see the reported bug). Escaping '$' -> '\\$' keeps dollar
    amounts as plain text while leaving normal markdown (bold, bullets) intact.
    """
    st.markdown((text or "").replace("$", "\\$"))


def _render_plan(plan):
    """The orchestrator's up-front reasoning — its target, approach, and the
    bar it set for a good answer. Collapsed by default (the answer is the hero),
    but available so the analyst can see HOW it thought before fetching."""
    if plan is None:
        return
    with st.expander("🧠 How the assistant approached this", expanded=False):
        st.markdown(f"**Target** — {plan.target}")
        st.markdown(f"**Approach** — {plan.approach}")
        st.markdown(f"**Representation** — {plan.representation}")
        st.markdown(f"**A good answer must** — {plan.success_criteria}")


def _render_live_answer(result):
    """Render a just-computed answer. The ANSWER is the hero: it renders first,
    with room to breathe; the trace and source data are quiet, collapsed
    drill-downs below a divider.
    """
    answer = result.answer

    if answer.type == "composed":
        # A composed analytical answer: narrative, then chart, then table.
        _prose(answer.value["narrative"])
        if answer.value.get("chart") is not None:
            _render_chart(answer.value["chart"])
        if answer.value.get("table") is not None:
            st.dataframe(_display_frame(answer.value["table"]), width='stretch')
    elif answer.type == "chart":
        _prose(answer.narration)
        _render_chart(answer.value)
    elif answer.type == "dataframe":
        _prose(answer.narration)
        st.dataframe(_display_frame(answer.value), width='stretch')
    elif answer.type == "number" and len(answer.narration or "") <= 120:
        # A metric is right ONLY for a genuinely short scalar answer ("the
        # average is 20"). When a number-typed answer carries a long analytical
        # narration (the model computed a scalar but wrote a full analysis about
        # it), a metric would cram the whole analysis into the label and show a
        # meaningless bare value — so fall through to prose instead.
        st.metric(label=answer.narration or "Result", value=format_number(answer.value))
    else:  # string, or a number with long-form analysis — prose, never a metric.
        _prose(answer.narration)

    st.divider()
    _render_plan(getattr(result, "plan", None))
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


def _render_chart(fig):
    """Render a chart at a controlled size — full-bleed matplotlib figures
    dwarf the surrounding text (the figure's native inches × Streamlit's DPI can
    be enormous). Cap the display size and don't stretch to the container width,
    so the plot reads as a chart in a conversation, not a poster."""
    # A sensible on-screen size regardless of what the generated code set.
    fig.set_size_inches(7, 3.6)
    fig.set_dpi(100)
    # Left-align in a bounded column rather than spanning the whole wide layout.
    col, _ = st.columns([3, 1])
    with col:
        st.pyplot(fig, use_container_width=True)


def _answer_figure(answer):
    """The matplotlib Figure in an answer, if any — a `chart` answer's value,
    or a `composed` answer's chart part. None for answers without a plot. Used
    to persist the plot so it survives a refresh (see the save block below)."""
    if answer.type == "chart":
        return answer.value
    if answer.type == "composed":
        return answer.value.get("chart")
    return None


def _figure_png(fig) -> bytes:
    """Render a matplotlib Figure to PNG bytes for durable storage."""
    import io
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    return buf.getvalue()


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
    if turn.answer_type == "number" and len(turn.narration or "") <= 120:
        st.metric(label=turn.narration or "Result", value=turn.value_preview)
    else:
        _prose(turn.narration)
        # A saved chart image is replayed (persisted as a PNG per turn); only a
        # table is still not restored (it isn't stored, and can be large).
        image = None
        try:
            image = catalog.load_turn_image(turn.id)
        except Exception:
            image = None
        if image is not None:
            st.image(image)
        elif turn.answer_type == "dataframe":
            st.caption(f"{turn.value_preview} — table not replayed on reload; ask again to regenerate.")
        elif turn.answer_type == "composed" and image is None:
            st.caption(f"{turn.value_preview} — table not replayed on reload; ask again to regenerate.")

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


def _scroll_to_active_turn():
    """Nudge the '#active-turn' anchor into view. Streamlit has no scroll API;
    a tiny HTML component runs JS in an iframe that reaches up to the parent
    document to scroll the anchor into view. Best-effort — a no-op if the
    browser blocks parent access."""
    import streamlit.components.v1 as components
    components.html(
        """
        <script>
        const doc = window.parent.document;
        const el = doc.getElementById("active-turn");
        if (el) { el.scrollIntoView({behavior: "smooth", block: "start"}); }
        </script>
        """,
        height=0,
    )


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
    # A clear break between the previous (completed) turn and this new one, so
    # the in-flight turn reads as the current activity — not as an overlay on
    # the previous answer while the (slow) loop runs and Streamlit dims prior
    # content. The anchor below is scrolled into view once the turn renders.
    if st.session_state.turns:
        st.divider()
    st.markdown('<div id="active-turn"></div>', unsafe_allow_html=True)

    with st.chat_message("user"):
        st.markdown(query)

    # Scroll the new turn into view so it's what the user is looking at while it
    # computes, rather than the previous (now-above) answer. Streamlit has no
    # native scroll API, so a tiny component nudges the anchor into view.
    _scroll_to_active_turn()

    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        with status_placeholder.container():
            status = st.status("Thinking…", expanded=True)
            thinking_placeholder = status.empty()
            stream_placeholder = status.empty()

        # Accumulate the loop's live decisions so the status box shows the
        # actual thinking — which step, why, what it's fetching — step by step,
        # instead of an opaque "Building the MRX plan...".
        thinking_log = []

        def _on_step(step_num, decision):
            if decision.action == "fetch":
                line = f"**{step_num}. Fetch** — {decision.reasoning}\n\n→ _{decision.fetch_query}_"
                status.update(label=f"Step {step_num}: fetching data…")
            elif decision.action == "analyze":
                line = f"**{step_num}. Analyze** — {decision.reasoning}"
                status.update(label="Analyzing the data…")
            else:  # respond
                line = f"**{step_num}. Answer directly** — {decision.reasoning}"
                status.update(label="Answering…")
            thinking_log.append(line)
            thinking_placeholder.markdown("\n\n".join(thinking_log))

        def _on_stage(stage):
            # Keep the coarse stage label only for sub-steps the decision
            # callback doesn't cover (plan/fetch/reuse within a fetch).
            if stage.startswith(("plan:", "fetch:", "reuse:")):
                status.update(label=_stage_label(stage))
            if stage != "answer":
                stream_placeholder.empty()

        def _on_token(buffer):
            stream_placeholder.code(buffer, language="python")

        try:
            result = loop.run_agent_loop(
                get_llm(), query, on_stage=_on_stage, on_step=_on_step, on_token=_on_token,
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
                # Persist the chart as a PNG so it survives a refresh/reopen —
                # a Figure can't go in SQLite, but its rendered image can live
                # on disk keyed by turn id.
                fig = _answer_figure(result.answer)
                if fig is not None:
                    catalog.save_turn_image(new_turn.id, _figure_png(fig))
            except Exception:
                pass
