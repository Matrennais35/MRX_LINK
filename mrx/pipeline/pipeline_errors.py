"""Typed errors for each stage of the NL -> MRX -> answer pipeline."""


class PipelineError(Exception):
    """Base class for all pipeline errors. `stage` names which step failed."""

    stage: str = "unknown"


class PlanGenerationError(PipelineError):
    stage = "get_link"


class PlanValidationError(PipelineError):
    stage = "validate_plan"


class DataFetchError(PipelineError):
    stage = "fetch_data"


class EmptyResultError(DataFetchError):
    pass


class AnswerError(PipelineError):
    stage = "answer"
