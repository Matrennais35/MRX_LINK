"""fetch_mrx — the MRX-expertise tool of the loop (the Task-subagent pattern).

Takes a NATURAL-LANGUAGE data request; inside: the nested URL-builder call
(the manuals/tables knowledge, never in the main context), the deterministic
validation gate with corrective retries, the HARD fetch budget, zero-cost
reuse, profiling, catalog persistence — all the proven machinery of
tools/mrx_fetch.fetch_evidence, reused unchanged.

Failures return as TEXT (not exceptions): the loop model reads the error and
corrects its request in the next iteration — in-loop self-correction, no
re-plan subsystem.
"""

from typing import Optional

from ...common.errors import BudgetExhausted, DataFetchError, PlanValidationError
from ...mrx import generate_link
from ...tools import mrx_fetch

MAX_URL_ATTEMPTS = 3

TOOL_DESCRIPTION = (
    "Fetch data from MRX. Describe the data you need in natural language — "
    "measure, scope/node, breakdown (single dimension), time form (snapshot / "
    "compare with T-1 / history dates window), filters. The tool builds and "
    "validates the MRX URL itself, reuses already-fetched data at zero cost, "
    "and registers the returned dataframe in your python namespace. Returns "
    "the dataframe's label and its profile."
)


def fetch(session, url_llm, view, request: str) -> str:
    """Run the gated fetch for one NL request; returns the tool-result text."""
    attempts = []
    for _ in range(MAX_URL_ATTEMPTS):
        plan = generate_link.get_link(url_llm, request, prior_attempts=attempts)
        try:
            evidence = mrx_fetch.fetch_evidence(plan, view, session, query=request)
        except PlanValidationError as e:
            attempts.append((plan, str(e)))
            continue
        except BudgetExhausted as e:
            return (f"FETCH REFUSED — {e}. Do not request more data; answer "
                    f"from what is already in the namespace.")
        except DataFetchError as e:
            return (f"FETCH FAILED — {e}\nMRX URL: {getattr(e, 'url', '')}\n"
                    f"Correct the request (parameters/window/scope) or proceed "
                    f"without this data.")
        session.register_frame(evidence.label, evidence.df)
        return (f"registered as '{evidence.label}' ({evidence.provenance})\n"
                f"{evidence.profile.render_text()}")
    last_error = attempts[-1][1] if attempts else "unknown validation error"
    return (f"FETCH FAILED — could not build a valid MRX view after "
            f"{MAX_URL_ATTEMPTS} attempts: {last_error}\nRephrase the request "
            f"(one breakdown dimension, a valid measure, explicit window).")
