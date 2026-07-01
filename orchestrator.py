"""Ties the pipeline stages together: plan -> validate -> fetch -> answer."""

from dataclasses import dataclass

import pandas as pd

import data_fetch
import generate_link
import smart_pandas
import validation
from generate_link import MRXPlan
from pipeline_errors import PlanGenerationError, PlanValidationError


@dataclass
class PipelineResult:
    plan: MRXPlan
    df: pd.DataFrame
    answer: str
    attempts: int


def _plan_and_validate(llm, query: str, *, min_confidence: float, max_attempts: int) -> tuple[MRXPlan, int]:
    """Build and validate a plan, feeding validation errors back to the LLM
    to self-correct, up to `max_attempts` tries. Raises the last error if
    every attempt is exhausted.
    """
    prior_attempts: list[tuple[MRXPlan, str]] = []

    for attempt in range(1, max_attempts + 1):
        try:
            plan = generate_link.get_link(llm, query, prior_attempts=prior_attempts)
        except Exception as e:
            if attempt == max_attempts:
                raise PlanGenerationError(f"Failed to build an MRX plan: {e}") from e
            continue

        try:
            validation.validate_plan(plan, min_confidence=min_confidence)
        except PlanValidationError as e:
            if attempt == max_attempts:
                raise
            prior_attempts.append((plan, str(e)))
            continue

        return plan, attempt

    # Unreachable: the loop always either returns or raises on the last attempt.
    raise AssertionError("plan/validate loop exited without returning or raising")


def run(llm, query: str, *, min_confidence: float = 0.7, max_attempts: int = 3) -> PipelineResult:
    """Run the full NL question -> MRX data -> answer pipeline.

    On a rejected plan (PlanValidationError) or a plan-generation failure,
    the error is sent back to the LLM and the plan is retried up to
    `max_attempts` times before giving up. Fetch and answer stages are
    single-shot: their failures aren't the LLM's to fix by retrying.

    Raises PlanGenerationError, PlanValidationError, DataFetchError, or
    AnswerError (all defined in pipeline_errors.py) if a stage fails or
    its output is unsafe to act on.
    """
    plan, attempts = _plan_and_validate(
        llm, query, min_confidence=min_confidence, max_attempts=max_attempts
    )
    df = data_fetch.fetch_data(plan.url)
    answer = smart_pandas.ask(df, plan.SmartDF, llm)
    return PipelineResult(plan=plan, df=df, answer=answer, attempts=attempts)
