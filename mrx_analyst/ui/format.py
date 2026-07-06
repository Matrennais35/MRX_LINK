"""Formats numbers for display: comma-separated, rounded to whole numbers.

Kept separate from the UI frontend so it's covered by a plain unit test —
the frontends themselves aren't tested here, but the formatting they share
can be.
"""

import pandas as pd


def format_number(value) -> str:
    """`1230123.456789` -> `"1,230,123"`. Non-numeric values pass through
    via str() unchanged. NaN/None render as an em-dash — legitimate gaps in
    computed tables (the trend table's first row has no prior-day Change;
    variance's pct_change is NaN when previous is 0), and round(NaN) crashes.
    """
    if isinstance(value, bool):
        return str(value)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, (int, float)):
        return f"{round(value):,}"
    return str(value)


def format_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """A copy of `df` with numeric columns formatted as display strings.

    Returns a copy rather than mutating `df` — callers may still need the
    original numeric values (e.g. for further computation), only the
    rendered copy should carry formatted strings.
    """
    formatted = df.copy()
    for column in formatted.select_dtypes(include="number").columns:
        formatted[column] = formatted[column].apply(format_number)
    return formatted
