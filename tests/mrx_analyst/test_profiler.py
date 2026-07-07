"""Tests for the deterministic data profiler."""

import pandas as pd
import pytest

from mrx_analyst.mrx import profiler


def _frame():
    return pd.DataFrame({
        "Book": ["A", "A", "B", "C"],
        "Pair": ["USDJPY", "USDCNH", "USDJPY", "EURHUF"],
        "fx_vega": [900.0, 300.0, -150.0, -50.0],
    })


def test_detects_the_value_column_and_computes_net_and_gross():
    p = profiler.profile(_frame())
    assert p.value_columns == ["fx_vega"]
    assert p.total_sum == 1000.0
    assert p.gross_positive == 1200.0
    assert p.gross_negative == -200.0
    assert p.sign_mix == {"pos": 2, "neg": 2, "zero": 0}


def test_strips_pre_aggregated_total_rows_from_statistics():
    df = _frame()
    df.loc[len(df)] = ["Total", "", 1000.0]  # the MRX pre-aggregated row
    p = profiler.profile(df)
    assert p.total_rows_excluded == 1
    assert p.total_sum == 1000.0  # NOT doubled to 2000 by the Total row


def test_concentration_per_low_cardinality_categorical():
    p = profiler.profile(_frame())
    by_book = next(c for c in p.categoricals if c.column == "Book")
    assert by_book.n_unique == 3
    assert by_book.top_groups[0] == "A"        # A holds 1200 of 1400 abs value
    assert by_book.top5_share == pytest.approx(1.0)
    assert 0.0 < by_book.hhi <= 1.0


def test_top_movers_ranked_by_absolute_value():
    p = profiler.profile(_frame())
    assert p.top_movers[0]["value"] == 900.0
    assert "A" in p.top_movers[0]["label"]


def test_wide_date_columns_detected_as_date_range():
    df = pd.DataFrame({
        "Risk Type": ["FX Vega"],
        "2026-06-01": [1.0], "2026-06-02": [2.0], "2026-06-30": [3.0],
    })
    p = profiler.profile(df)
    assert p.date_range == {"min": "2026-06-01", "max": "2026-06-30"}
    assert len(p.date_columns) == 3


def test_render_text_is_compact_and_prompt_safe():
    text = profiler.profile(_frame()).render_text()
    assert "net sum: 1,000" in text
    assert "by Book" in text
    assert len(text.splitlines()) <= 40


def test_never_raises_on_odd_frames():
    assert profiler.profile(pd.DataFrame()).rows == 0
    assert profiler.profile(pd.DataFrame({"only_text": ["a", "b"]})).value_columns == []
