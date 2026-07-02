"""Streamlit frontend over the mrx pipeline. See main.py for the CLI frontend.

Run with: streamlit run app.py
"""

import html

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from mrx import connect_llm, orchestrator
from mrx.errors_display import describe_error
from mrx.number_display import format_number, format_numeric_columns
from mrx.pipeline_errors import PipelineError

st.set_page_config(page_title="MRX Link", page_icon="◆", layout="centered")


def _session_id() -> str:
    # Ties dataset-reuse scoping (mrx/catalog.py) to this actual browser
    # session, rather than every user sharing orchestrator.DEFAULT_SESSION_ID
    # — without this, "prefer this conversation's own recent fetches" never
    # runs, every reuse candidate is just ranked by recency across all users.
    ctx = get_script_run_ctx()
    return ctx.session_id if ctx else orchestrator.DEFAULT_SESSION_ID

# Design notes (see also .streamlit/config.toml for the base widget theme):
# dark terminal palette — this is a query tool for an internal risk system,
# not a consumer product, so it's styled closer to a trading-desk instrument
# panel than a chat assistant. IBM Plex Mono/Sans because they're designed
# as a matched family (share metrics/proportions) and the mono face gives
# every ticker, date, and number real visual weight instead of being an
# afterthought. Amber is the one accent color, spent on the answer number
# and active states — everything else stays quiet (hairlines, muted labels).
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500&display=swap');

:root {
    --bg: #0A0B0D;
    --panel: #141619;
    --text: #C9CDD3;
    --muted: #6B7280;
    --amber: #E8A33D;
    --line: #2A2E33;
}

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }

.mrx-header {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    padding-bottom: 0.25rem;
    border-bottom: 1px solid var(--line);
    margin-bottom: 0.4rem;
}
.mrx-header .mark { color: var(--amber); font-family: 'IBM Plex Mono', monospace; font-size: 1.4rem; }
.mrx-header .name {
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 700;
    font-size: 1.4rem;
    letter-spacing: 0.08em;
    color: var(--text);
}
.mrx-tagline { color: var(--muted); font-size: 0.85rem; margin-bottom: 1.6rem; }

.mrx-eyebrow {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    color: var(--muted);
    text-transform: uppercase;
    margin: 1.4rem 0 0.4rem 0;
}

/* Terminal-prompt styling for the question input */
div[data-testid="stTextInput"] input {
    font-family: 'IBM Plex Mono', monospace !important;
    background-color: var(--panel) !important;
    border: 1px solid var(--line) !important;
    color: var(--text) !important;
}
div[data-testid="stTextInput"] label { display: none; }

/* Ticker-style scalar answer: the one place boldness is spent */
.mrx-ticker { margin: 0.6rem 0 1rem 0; }
.mrx-ticker .label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    letter-spacing: 0.1em;
    color: var(--muted);
    text-transform: uppercase;
}
.mrx-ticker .value {
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    font-size: 2.6rem;
    color: var(--amber);
    line-height: 1.15;
}

code, .stCodeBlock, pre { font-family: 'IBM Plex Mono', monospace !important; }

.mrx-stream {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.8rem;
    color: var(--muted);
    background-color: var(--panel);
    border: 1px solid var(--line);
    border-radius: 2px;
    padding: 0.6rem 0.8rem;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 220px;
    overflow-y: auto;
}
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="mrx-header"><span class="mark">◆</span><span class="name">MRX&nbsp;LINK</span></div>'
    '<div class="mrx-tagline">Ask a market-risk question in plain English.</div>',
    unsafe_allow_html=True,
)


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

st.markdown('<div class="mrx-eyebrow">Query</div>', unsafe_allow_html=True)
query = st.text_input(
    "Question",
    key="query",
    placeholder="> what is the average EQ PV Diff between 2026-05-30 and 2026-06-03 for US_SPX in GLEQD?",
    label_visibility="collapsed",
)

st.markdown('<div class="mrx-eyebrow">Examples</div>', unsafe_allow_html=True)
example_cols = st.columns(len(EXAMPLE_QUESTIONS))
for col, example in zip(example_cols, EXAMPLE_QUESTIONS):
    if col.button(example, use_container_width=True):
        st.session_state.query = example
        st.rerun()

_run = st.button("Run query", disabled=not query, type="primary")

if _run:
    status = st.status(STAGE_LABELS["plan"], expanded=True)
    stream_placeholder = status.empty()

    def _on_stage(stage):
        status.update(label=_stage_label(stage))
        if stage != "answer":
            stream_placeholder.empty()

    def _on_token(buffer):
        # Live view of the LLM writing pandas code / narrating the result,
        # during the "answer" stage — the two are visually indistinguishable
        # here (both are just raw streamed text), which is honest: this is
        # literally what the model is emitting, not a curated summary of it.
        # Escaped since streamed code routinely contains "<"/">"/"&" (e.g.
        # df[df["value"] > 2]), which would otherwise corrupt the injected HTML.
        escaped = html.escape(buffer)
        stream_placeholder.markdown(f'<div class="mrx-stream">{escaped}</div>', unsafe_allow_html=True)

    try:
        result = orchestrator.run(
            get_llm(), query, on_stage=_on_stage, on_token=_on_token, session_id=_session_id(),
            allow_multi_fetch=True,
        )
    except PipelineError as e:
        status.update(label="Failed", state="error", expanded=True)
        st.error(describe_error(e))
        result = None
    else:
        stream_placeholder.empty()
        status.update(label="Done", state="complete", expanded=False)

    if result is not None:
        st.markdown('<div class="mrx-eyebrow">Answer</div>', unsafe_allow_html=True)
        st.write(result.answer.narration)

        if result.answer.type == "chart":
            st.pyplot(result.answer.value)
        elif result.answer.type == "dataframe":
            st.dataframe(format_numeric_columns(result.answer.value))
        else:
            st.markdown(
                f'<div class="mrx-ticker">'
                f'<div class="label">Computed value</div>'
                f'<div class="value">{format_number(result.answer.value)}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )

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
            if result.answer.method:
                st.markdown(f"**Method:** {result.answer.method}")
            st.markdown("**Code that was run:**")
            st.code(result.answer.code, language="python")
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
