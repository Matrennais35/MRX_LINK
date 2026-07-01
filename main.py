import connect_llm
import orchestrator
from pipeline_errors import AnswerError, DataFetchError, PlanGenerationError, PlanValidationError

llm = connect_llm.get_llm(model='gpt55', version="2024-06-01")
query = "What is the average between COB 2026-06-03 and 2026-05-30 for EQ PV Diff at spot -10 for US_SPX in GLEQD"

try:
    result = orchestrator.run(llm, query)
except PlanGenerationError as e:
    print(f"Could not build an MRX plan: {e}")
except PlanValidationError as e:
    print(f"Could not build a valid MRX link: {e}")
except DataFetchError as e:
    print(f"Could not fetch data from MRX: {e}")
except AnswerError as e:
    print(f"Could not answer the question over the data: {e}")
else:
    print(result.answer.value)
    if result.attempts > 1:
        print(f"(took {result.attempts} attempts to build a valid MRX plan)")
