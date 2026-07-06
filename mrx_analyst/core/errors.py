"""Typed errors for the mrx_analyst pipeline.

Ported from the proven hierarchy (stage-tagged, URL-carrying so a failed MRX
fetch can surface the exact link to open and diagnose), plus BudgetExhausted —
the plain-code signal that the global fetch budget refused another fetch.
"""

from typing import Optional


class PipelineError(Exception):
    """Base class for all pipeline errors. `stage` names which step failed;
    `url`, when set, is the MRX URL involved (a failed fetch is far more
    actionable when the user can see and click the link that produced it).
    """

    stage: str = "unknown"

    def __init__(self, *args, url: Optional[str] = None):
        super().__init__(*args)
        self.url = url


class PlanGenerationError(PipelineError):
    stage = "plan"


class PlanValidationError(PipelineError):
    stage = "validate"


class DataFetchError(PipelineError):
    stage = "fetch"


class EmptyResultError(DataFetchError):
    pass


class AnswerError(PipelineError):
    stage = "answer"


class BudgetExhausted(PipelineError):
    """The global fetch budget refused another fetch. Raised by
    FetchBudget.acquire() in plain code — never a model's or framework's call.
    The orchestrator catches it to stop the fetch phase and proceed with the
    evidence gathered so far (it is NOT a user-facing failure).
    """

    stage = "budget"

    def __init__(self, used: int, max_fetches: int):
        super().__init__(f"fetch budget exhausted ({used}/{max_fetches} used)")
        self.used = used
        self.max_fetches = max_fetches
