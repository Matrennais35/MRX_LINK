"""CLI frontend over the mrx pipeline. See app.py for the Streamlit frontend."""

from mrx import connect_llm, orchestrator
from mrx.errors_display import describe_error
from mrx.pipeline_errors import PipelineError

llm = connect_llm.get_llm(model='gpt55', version="2024-06-01")
query = "What is the average between COB 2026-06-03 and 2026-05-30 for EQ PV Diff at spot -10 for US_SPX in GLEQD"

try:
    result = orchestrator.run(llm, query)
except PipelineError as e:
    print(describe_error(e))
else:
    print(result.answer.narration)
    if result.answer.type == "chart":
        print("(a chart was produced — run this via the Streamlit UI, app.py, to view it)")
    else:
        print(f"(computed value: {result.answer.value!r})")
    if result.answer.method:
        print(f"(method: {result.answer.method})")
    if result.attempts > 1:
        print(f"(took {result.attempts} attempts to build a valid MRX plan)")
