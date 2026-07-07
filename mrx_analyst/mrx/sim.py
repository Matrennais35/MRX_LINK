"""The MRX SIMULATOR — the whole framework on fake data (MRX_SIM=1).

A stand-in for the multirow view that goes through the REAL validation gate
and parses the REAL URL parameters, then synthesizes frames in the exact
shapes the live view returns (wide history with date columns, compare with
Total/prv/diff, Risk Explain with New/Passive/Expired, Depth hierarchies,
deal labels with maturities, Total rows).

The world is DETERMINISTIC (seeded by node+measure) and carries a PLANTED
STORY — a dated jump driven by specific names with a known explain split —
exposed via .truth(), so an evaluation can check the ANSWER against ground
truth, which no live run can do.

Uses: run the app/harnesses offline or without touching production MRX
(demo mode); ground-truth evals; letting the framework be exercised
end-to-end wherever pymrx doesn't exist.
"""

import zlib
from datetime import date, timedelta
from urllib.parse import parse_qsl, unquote, urlparse

import numpy as np
import pandas as pd

from . import validation

# Label pools per row-grouping code family (keyword-matched; any valid code
# gets plausible labels even if unlisted).
_PAIRS = ["USDHKD", "USDCNH", "EURUSD", "EURHUF", "USDBRL", "USDCAD", "USDZAR",
          "EURBRL", "USDTRY", "EURMXN", "USDINR", "USDJPY", "EURPLN", "EURCNH",
          "USDCOP", "GBPUSD", "AUDUSD", "USDKRW", "EURGBP", "USDMXN"]
_CCYS = ["USD", "EUR", "JPY", "GBP", "HKD", "CNH", "BRL", "TRY", "MXN", "ZAR"]
_BOOKS = ["FXO_EM_ASIA", "FXO_EM_LATAM", "FXO_G10_DESK", "FXO_EXOTICS",
          "FXO_CORP_FLOW", "FXO_PROP_1", "FXO_STRUCT", "FXO_HEDGE"]
_PRODUCTS = ["Vanilla Option", "FX Target", "Barrier KO", "Digital",
             "Variance Swap", "Forward", "Accumulator"]
_EXPLAIN = ["New", "Passive", "Expired"]


def _business_days(start: date, end: date):
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


class SimMRXView:
    """Duck-types the live multirow view: validate / execute / fingerprint."""

    name = "sim"

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.executed = 0

    # -- the REAL gate: the simulator only serves URLs the live view would --
    def validate(self, plan, **kw):
        validation.validate_plan(plan, **kw)

    def fingerprint(self, plan):
        return dict(parse_qsl(urlparse(plan.url).query))

    # -- the world ----------------------------------------------------------
    def _rng(self, node: str, measure: str):
        # zlib.crc32, NOT hash(): Python string hashing is salted per process,
        # which would give every restart a different 'deterministic' world
        # (found by self-driving this simulator — truth() must be stable).
        return np.random.default_rng(
            zlib.crc32(f"{node}|{measure}|{self.seed}".encode()))

    def truth(self, node: str, measure: str, end: date, start: date) -> dict:
        """The planted story for this world slice — the eval's ground truth."""
        days = _business_days(start, end)
        rng = self._rng(node, measure)
        base = self._base_book(rng)
        jump_day = days[-3] if len(days) >= 3 else days[-1]
        return {
            "jump_date": jump_day.isoformat(),
            "jump_driver": _PAIRS[0],           # USDHKD builds NEW positions
            "jump_second": _PAIRS[1],
            "jump_offset": _PAIRS[2],
            "explain_split": {"New": 0.70, "Passive": 0.35, "Expired": -0.05},
            "base_total": float(sum(base.values())),
        }

    def _base_book(self, rng) -> dict:
        mags = rng.uniform(0.2e6, 4e6, size=len(_PAIRS))
        signs = rng.choice([1, 1, 1, -1], size=len(_PAIRS))
        return dict(zip(_PAIRS, mags * signs))

    def _series(self, node, measure, days):
        """value[label][day] — a drifting book with the planted jump."""
        rng = self._rng(node, measure)
        base = self._base_book(rng)
        jump_idx = max(len(days) - 3, 0)
        # ABSOLUTE jump sizes (not relative to each pair's random base): the
        # planted ranking must hold in the data by construction, or truth()
        # and the frames could disagree on who the driver is.
        jumps = {_PAIRS[0]: 4.0e6, _PAIRS[1]: 1.5e6, _PAIRS[2]: -2.0e6}
        out = {}
        for label, level in base.items():
            noise = rng.normal(0, abs(level) * 0.03, size=len(days)).cumsum()
            series = level + noise
            series[jump_idx:] += jumps.get(label, 0.0)
            out[label] = series
        return out

    # -- URL -> frame --------------------------------------------------------
    def execute(self, plan) -> pd.DataFrame:
        self.executed += 1
        params = {k: unquote(v) for k, v in
                  parse_qsl(urlparse(plan.url).query)}
        node = params.get("p1", "NODE")
        measure = params.get("p13", "MEASURE")
        end = date.fromisoformat(params["p27"])
        start = date.fromisoformat(params.get("p28", params["p27"]))
        row_code = params.get("p1217", "RowGrpUnderlying")
        col_form = params.get("p1029", "Total")
        col_sel = params.get("p1021", "Current")
        filters = [f for f in params.get("p17", "").split(",") if f]

        days = _business_days(start, end) or [end]
        series = self._series(node, measure, days)

        if "riskexpain" in row_code.lower():
            return self._explain_frame(node, measure, days, series)

        labels = self._labels_for(row_code, series)
        if filters:
            labels = [l for l in labels if any(f.lower() in l.lower() for f in filters)]
        values = self._values_for(labels, row_code, series)

        if "history" in col_form.lower():
            return self._history_frame(labels, values, days)
        if "Difference" in col_sel or "Previous" in col_sel:
            return self._compare_frame(labels, values, days)
        return self._snapshot_frame(labels, values)

    # -- label semantics per grouping code ------------------------------------
    def _labels_for(self, row_code, series):
        code = row_code.lower()
        if "underlying" in code:
            return list(series)
        if "currency" in code:
            return _CCYS
        if "book" in code or "portfolio" in code or "folio" in code:
            return _BOOKS
        if "prdinl" in code or "deal" in code.replace("rowgrp", ""):
            rng = np.random.default_rng(7)
            deals = []
            for i in range(30):
                mat = date(2026, 1, 1) + timedelta(days=int(rng.integers(30, 900)))
                deals.append(f"FXO-{1800000 + i * 137}/1 | FXO STND "
                             f"{'Put' if i % 2 else 'Call'} {mat.isoformat()}")
            return deals
        if "product" in code:
            return _PRODUCTS
        return [f"{row_code}_{i}" for i in range(1, 9)]

    def _values_for(self, labels, row_code, series):
        """Per-label daily values: underlyings use the planted series; other
        groupings get a deterministic reallocation of the same book total."""
        if labels and labels[0] in series:
            return {l: series[l] for l in labels}
        total = np.sum([v for v in series.values()], axis=0)
        rng = np.random.default_rng(zlib.crc32(row_code.encode()))
        weights = rng.dirichlet(np.ones(len(labels))) if labels else []
        return {l: total * w for l, w in zip(labels, weights)}

    # -- the four live frame shapes -------------------------------------------
    def _history_frame(self, labels, values, days):
        cols = [d.strftime("%Y/%m/%d") for d in days]
        rows = [{"Depth": 0, "Label": "Total",
                 **{c: float(np.sum([values[l][i] for l in labels]))
                    for i, c in enumerate(cols)}}]
        for l in labels:
            rows.append({"Depth": 1, "Label": l,
                         **{c: float(values[l][i]) for i, c in enumerate(cols)}})
        return pd.DataFrame(rows)

    def _compare_frame(self, labels, values, days):
        rows = [{"Depth": 0, "Label": "Total",
                 "Total": float(np.sum([values[l][-1] for l in labels])),
                 "Total (prv)": float(np.sum([values[l][0] for l in labels]))}]
        for l in labels:
            rows.append({"Depth": 1, "Label": l,
                         "Total": float(values[l][-1]),
                         "Total (prv)": float(values[l][0])})
        df = pd.DataFrame(rows)
        df["Total (diff)"] = df["Total"] - df["Total (prv)"]
        return df

    def _snapshot_frame(self, labels, values):
        rows = [{"Depth": 0, "Label": "Total",
                 "Total": float(np.sum([values[l][-1] for l in labels]))}]
        rows += [{"Depth": 1, "Label": l, "Total": float(values[l][-1])}
                 for l in labels]
        return pd.DataFrame(rows)

    def _explain_frame(self, node, measure, days, series):
        """Risk Explain compare: New/Passive/Expired reconciling to the move."""
        total_start = float(np.sum([v[0] for v in series.values()]))
        total_end = float(np.sum([v[-1] for v in series.values()]))
        move = total_end - total_start
        split = {"New": 0.70 * move, "Passive": 0.35 * move, "Expired": -0.05 * move}
        rows = []
        for cause, delta in split.items():
            prv = 0.0 if cause == "New" else (total_start if cause == "Passive"
                                              else abs(delta))
            cur = 0.0 if cause == "Expired" else prv + delta
            rows.append({"Depth": 0, "Risk Component": cause,
                         "Total": cur, "Total (prv)": prv, "Total (diff)": delta})
            rows.append({"Depth": 1, "Risk Component": f"{cause} / {measure}",
                         "Total": cur, "Total (prv)": prv, "Total (diff)": delta})
        return pd.DataFrame(rows)
