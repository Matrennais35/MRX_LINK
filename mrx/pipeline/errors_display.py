"""Maps a pipeline error to a short, user-facing message.

Kept separate from the UI frontend so it's covered by a plain unit test —
the frontends themselves (main.py, app.py) aren't tested here, but the
message mapping they share can be.
"""

from .pipeline_errors import AnswerError, DataFetchError, PlanGenerationError, PlanValidationError


def describe_error(error: Exception) -> str:
    """A short, user-facing message for one of the pipeline's typed errors."""
    if isinstance(error, PlanGenerationError):
        return f"Could not build an MRX plan: {error}"
    if isinstance(error, PlanValidationError):
        return f"Could not build a valid MRX link: {error}"
    if isinstance(error, DataFetchError):
        return f"Could not fetch data from MRX: {error}"
    if isinstance(error, AnswerError):
        return f"Could not answer the question over the data: {error}"
    raise TypeError(f"not a recognized pipeline error: {type(error)}")
