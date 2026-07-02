import pandas as pd
import pytest

from mrx.pipeline.number_display import format_number, format_numeric_columns


@pytest.mark.parametrize("value,expected", [
    (1230123.456789, "1,230,123"),
    (1230123, "1,230,123"),
    (0, "0"),
    (-1230123.6, "-1,230,124"),
    (2.5, "2"),  # Python's round() uses banker's rounding (round-half-to-even)
    (0.4, "0"),
])
def test_format_number_rounds_and_comma_separates(value, expected):
    assert format_number(value) == expected


def test_format_number_passes_through_non_numeric_values():
    assert format_number("Total") == "Total"
    assert format_number(None) == "None"


def test_format_number_does_not_mangle_booleans():
    # bool is a subclass of int in Python; guard against "True" -> "1".
    assert format_number(True) == "True"
    assert format_number(False) == "False"


def test_format_numeric_columns_formats_only_numeric_columns():
    df = pd.DataFrame({
        "underlying": ["US_SPX", "US_NDX"],
        "pv_diff": [1230123.456789, -45.6],
    })
    formatted = format_numeric_columns(df)
    assert list(formatted["underlying"]) == ["US_SPX", "US_NDX"]
    assert list(formatted["pv_diff"]) == ["1,230,123", "-46"]


def test_format_numeric_columns_does_not_mutate_the_original():
    df = pd.DataFrame({"value": [1230123.456789]})
    format_numeric_columns(df)
    assert df["value"].iloc[0] == 1230123.456789
