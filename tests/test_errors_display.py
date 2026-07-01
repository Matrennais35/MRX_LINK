import pytest

from mrx.errors_display import describe_error
from mrx.pipeline_errors import AnswerError, DataFetchError, PlanGenerationError, PlanValidationError


@pytest.mark.parametrize("error_cls,expected_prefix", [
    (PlanGenerationError, "Could not build an MRX plan:"),
    (PlanValidationError, "Could not build a valid MRX link:"),
    (DataFetchError, "Could not fetch data from MRX:"),
    (AnswerError, "Could not answer the question over the data:"),
])
def test_describe_error_maps_each_pipeline_error(error_cls, expected_prefix):
    message = describe_error(error_cls("details"))
    assert message.startswith(expected_prefix)
    assert "details" in message


def test_describe_error_rejects_unknown_exception_types():
    with pytest.raises(TypeError):
        describe_error(ValueError("not a pipeline error"))
