"""Streamlit frontend over the mrx pipeline. See main.py for the CLI frontend.

Run with: streamlit run app.py
"""

import streamlit as st

from mrx import connect_llm, orchestrator
from mrx.errors_display import describe_error
from mrx.number_display import format_number, format_numeric_columns
from mrx.pipeline_errors import PipelineError

st.set_page_config(page_title="MRX Link", page_icon="📊")
st.title("MRX Link")
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
    "fetch": "Fetching data from MRX...",
    "answer": "Computing the answer...",
}

query = st.text_input(
    "Question",
    key="query",
    placeholder="What is the average EQ PV Diff between 2026-05-30 and 2026-06-03 for US_SPX in GLEQD?",
)

st.caption("Try one of these:")
example_cols = st.columns(len(EXAMPLE_QUESTIONS))
for col, example in zip(example_cols, EXAMPLE_QUESTIONS):
    if col.button(example, use_container_width=True):
        st.session_state.query = example
        st.rerun()

_run = st.button("Ask", disabled=not query, type="primary")

if _run:
    status = st.status(STAGE_LABELS["plan"], expanded=False)
    try:
        result = orchestrator.run(
            get_llm(), query, on_stage=lambda stage: status.update(label=STAGE_LABELS[stage])
        )
    except PipelineError as e:
        status.update(label="Failed", state="error")
        st.error(describe_error(e))
        result = None
    else:
        status.update(label="Done", state="complete")

    if result is not None:
        st.subheader("Answer")
        st.write(result.answer.narration)
        if result.answer.type == "chart":
            st.pyplot(result.answer.value)
        elif result.answer.type == "dataframe":
            st.dataframe(format_numeric_columns(result.answer.value))
        else:
            st.caption(f"Computed value: {format_number(result.answer.value)}")

        if result.attempts > 1:
            st.caption(f"Took {result.attempts} attempts to build a valid MRX plan.")

        with st.expander("How was this computed?"):
            if result.answer.method:
                st.markdown(f"**Method:** {result.answer.method}")
            st.markdown("**Code that was run:**")
            st.code(result.answer.code, language="python")
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
