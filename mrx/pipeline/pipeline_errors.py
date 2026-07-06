"""Typed errors for each stage of the NL -> MRX -> answer pipeline."""


class PipelineError(Exception):
    """Base class for all pipeline errors. `stage` names which step failed;
    `url`, when set, is the MRX URL involved (so a failed fetch can surface
    the exact link for the user to open and diagnose — an MRX 500 is far more
    actionable when you can see and click the URL that produced it).
    """

    stage: str = "unknown"

    def __init__(self, *args, url: str = None):
        super().__init__(*args)
        self.url = url


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
