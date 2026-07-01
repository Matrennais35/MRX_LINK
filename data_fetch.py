"""Fetch data from MRX for a validated URL."""

import pandas as pd
import pymrx

from pipeline_errors import DataFetchError, EmptyResultError


def fetch_data(url: str) -> pd.DataFrame:
    """Download the dataframe an MRX URL points to."""
    try:
        df = pymrx.from_link(url).get_data()
    except Exception as e:
        raise DataFetchError(f"Failed to fetch data from MRX: {e}") from e

    if df is None or df.empty:
        raise EmptyResultError(f"MRX returned no data for URL: {url}")

    return df
