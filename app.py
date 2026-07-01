"""Streamlit frontend over the mrx pipeline. See main.py for the CLI frontend.

Run with: streamlit run app.py
"""

import streamlit as st

from mrx import connect_llm, orchestrator
from mrx.errors_display import describe_error
from mrx.pipeline_errors import PipelineError

st.set_page_config(page_title="MRX Link", page_icon="📊")
st.title("MRX Link")
st.caption("Ask a market-risk question in plain English.")


@st.cache_resource
def get_llm():
    return connect_llm.get_llm(model="gpt55", version="2024-06-01")


query = st.text_input(
    "Question",
    placeholder="What is the average EQ PV Diff between 2026-05-30 and 2026-06-03 for US_SPX in GLEQD?",
)

if st.button("Ask", disabled=not query):
    with st.spinner("Building the MRX plan and fetching data..."):
        try:
            result = orchestrator.run(get_llm(), query)
        except PipelineError as e:
            st.error(describe_error(e))
        else:
            st.subheader("Answer")
            st.write(result.answer.narration)
            if result.answer.type == "dataframe":
                st.dataframe(result.answer.value)
            else:
                st.caption(f"Computed value: {result.answer.value!r}")

            if result.attempts > 1:
                st.caption(f"Took {result.attempts} attempts to build a valid MRX plan.")

            with st.expander("Plan details"):
                st.markdown(f"**Intent:** {result.plan.intent}")
                st.markdown(f"**Reasoning:** {result.plan.view_reasoning}")
                if result.plan.assumptions:
                    st.markdown("**Assumptions:**")
                    for assumption in result.plan.assumptions:
                        st.markdown(f"- {assumption}")
                st.markdown(f"**Confidence:** {result.plan.confidence:.2f}")
                st.markdown(f"**MRX URL:** `{result.plan.url}`")
