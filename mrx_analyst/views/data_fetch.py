"""Fetch data from MRX for a validated URL."""

import pandas as pd
import pymrx

from ..core.errors import DataFetchError, EmptyResultError


def fetch_data(url: str) -> pd.DataFrame:
    """Download the dataframe an MRX URL points to."""
    try:
        df = pymrx.from_link(url).get_data()
    except Exception as e:
        # Carry the URL on the error so the UI can show the exact MRX link that
        # failed — an MRX 500/timeout is only actionable if you can open it.
        raise DataFetchError(f"Failed to fetch data from MRX: {e}", url=url) from e

    if df is None or df.empty:
        raise EmptyResultError(f"MRX returned no data for this link.", url=url)

    return df
