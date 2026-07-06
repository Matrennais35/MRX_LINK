"""The Streamlit shell: identity, history replay, the chat loop, live events.

Presentation only — run_turn owns the pipeline AND persistence (turn, trace,
chart PNG all saved inside it, so headless runs persist identically). This
shell renders history, streams live events from the ONE emit channel, renders
the Answer, and captures feedback.
"""

from dataclasses import dataclass

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from ..core import llm as llm_factory
from ..core import orchestrator
from ..core.errors import PipelineError
from ..storage import catalog
from . import render, sidebar

EXAMPLE_QUESTIONS = [
    "Analyse the variation of FX Vega on GFXOPEMK over the last month.",
    "Which desk drove the biggest IR Delta change on IRUS this week, and which deals within it?",
    "Plot the FX Vega evolution of USDJPY under GFXOPEMK for June 2026.",
]


@st.cache_resource
def get_llm():
    return llm_factory.get_llm(model="gpt55", version="2024-06-01")


@dataclass
class _FailedTurn:
    question: str
    error_message: str
    url: str = ""


def _session_id() -> str:
    ctx = get_script_run_ctx()
    return ctx.session_id if ctx else "default"


def _conversation_id() -> str:
    existing = st.query_params.get("c")
    if existing:
        return existing
    new_id = catalog.new_conversation_id()
    st.query_params["c"] = new_id
    return new_id


def _render_history_item(item) -> None:
    # Duck-typed, not isinstance: Streamlit redefines _FailedTurn each rerun,
    # so isinstance against a session_state-stashed instance fails.
    with st.chat_message("user"):
        st.markdown(item.question)
    with st.chat_message("assistant"):
        if hasattr(item, "error_message"):
            render.render_error(item.error_message, getattr(item, "url", ""))
        else:
            render.render_past_turn(item)
            render.render_feedback_form(
                item.id, item.conversation_id, item.question,
                st.session_state.get("plans", {}).get(item.id),
            )


def _make_emit(status, thinking_placeholder, stream_placeholder):
    """Route the ONE event channel into the live status box."""
    thinking_log = []

    def emit(kind, payload):
        if kind == "status":
            status.update(label=payload["label"])
        elif kind == "agent":
            role = payload["role"]
            out = payload.get("output", {})
            line = out.get("reasoning") or out.get("target") or out.get("verdict") or ""
            thinking_log.append(f"**{role}** — {line}" if line else f"**{role}**")
            thinking_placeholder.markdown("\n\n".join(thinking_log))
        elif kind == "fetch":
            stage, label = payload.get("stage"), payload.get("label", "")
            if stage in ("fetching", "reused", "done"):
                thinking_log.append(f"· *{stage}*: {label}")
                thinking_placeholder.markdown("\n\n".join(thinking_log))
        elif kind == "token":
            stream_placeholder.markdown((payload.get("text") or "").replace("$", "\\$"))
        elif kind == "error":
            thinking_log.append(f"⚠ {payload.get('message', '')}")
            thinking_placeholder.markdown("\n\n".join(thinking_log))

    return emit


def main() -> None:
    st.set_page_config(page_title="MRX Analyst", page_icon="◆", layout="wide")
    st.title("◆ MRX Analyst")
    st.caption("Ask a market-risk question — a team of specialist agents plans, "
               "fetches, computes, and writes the analysis.")

    conversation_id = _conversation_id()
    sidebar.render(conversation_id, _session_id())

    if "turns" not in st.session_state:
        st.session_state.turns = catalog.list_turns(conversation_id=conversation_id)

    for item in st.session_state.turns:
        _render_history_item(item)

    clicked_example = None
    if not st.session_state.turns:
        st.caption("Examples")
        cols = st.columns(len(EXAMPLE_QUESTIONS))
        for col, example in zip(cols, EXAMPLE_QUESTIONS):
            if col.button(example, use_container_width=True):
                clicked_example = example

    query = st.chat_input("Ask a market-risk question, or a follow-up...") or clicked_example
    if not query:
        return

    if st.session_state.turns:
        st.divider()

    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        with status_placeholder.container():
            status = st.status("Thinking…", expanded=True)
            thinking_placeholder = status.empty()
            stream_placeholder = status.empty()

        emit = _make_emit(status, thinking_placeholder, stream_placeholder)

        try:
            result = orchestrator.run_turn(
                get_llm(), query,
                session_id=_session_id(), conversation_id=conversation_id, emit=emit,
            )
        except PipelineError as e:
            status.update(label="Failed", state="error", expanded=True)
            message = f"{type(e).__name__}: {e}"
            failed_url = getattr(e, "url", None) or ""
            render.render_error(message, failed_url)
            st.session_state.turns.append(
                _FailedTurn(question=query, error_message=message, url=failed_url))
            return

        status_placeholder.empty()
        render.render_answer(result.answer)
        st.divider()
        render.render_plan(result.ctx.plan)
        render.render_trace(result.ctx.trace)
        render.render_evidence(result.ctx.evidence)

        # run_turn already persisted the turn/trace/chart — the app only tracks
        # session replay state + the plan for the feedback form.
        turn = catalog.Turn(
            id=result.turn_id, conversation_id=conversation_id, created_at="",
            question=query, narration=result.answer.narrative, method="",
            answer_type="answer", value_preview="", code="",
        )
        st.session_state.turns.append(turn)
        st.session_state.setdefault("plans", {})[result.turn_id] = result.ctx.plan
        render.render_feedback_form(result.turn_id, conversation_id, query, result.ctx.plan)
