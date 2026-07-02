import pandas as pd
import pytest

from mrx.pipeline.data_fetch import fetch_data
from mrx.pipeline.pipeline_errors import DataFetchError, EmptyResultError


def test_fetch_data_returns_dataframe(fake_pymrx):
    fake_pymrx["df"] = pd.DataFrame({"value": [1, 2, 3]})
    df = fetch_data("https://fake-url")
    assert df.shape == (3, 1)


def test_fetch_data_raises_on_empty_result(fake_pymrx):
    fake_pymrx["mode"] = "empty"
    with pytest.raises(EmptyResultError):
        fetch_data("https://fake-url")


def test_fetch_data_wraps_transport_errors(fake_pymrx):
    fake_pymrx["mode"] = "raises"
    with pytest.raises(DataFetchError):
        fetch_data("https://fake-url")


def test_empty_result_error_is_a_data_fetch_error(fake_pymrx):
    fake_pymrx["mode"] = "empty"
    with pytest.raises(DataFetchError):
        fetch_data("https://fake-url")
