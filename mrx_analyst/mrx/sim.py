"""The MRX SIMULATOR — the whole framework on fake data (MRX_SIM=1).

A stand-in for the multirow view that goes through the REAL validation gate
and parses the REAL URL parameters, then synthesizes frames in the exact
shapes the live view returns (wide history with date columns, compare with
Total/prv/diff, Risk Explain with New/Passive/Expired, Depth hierarchies,
deal labels with maturities, Total rows).

THE WORLD IS FACTORED: the atomic unit is a cell (underlying, product, book).
Base levels distribute over products/books PROPORTIONALLY (outer product of
dirichlet marginals) while the planted jump is CONCENTRATED (USDHKD's build
is 90% "FX Target") — so a multi-dimension sweep finds underlying and product
informative and books/portfolios correctly diffuse. Any grouping is a
marginalization of the same cells and FILTERS ARE SLICES of the same cells,
so every cut and cross-cut reconciles to the same net by construction.

The world is DETERMINISTIC (crc32-seeded — never hash(), which is process-
salted) and ABSOLUTE in time (values are functions of the DATE, identical
whatever window a query asks for). The planted story is exposed via
.truth() so an evaluation can check the ANSWER against ground truth, which
no live run can do.
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

# The planted story (absolute sizes so the ranking holds by construction).
_JUMPS = {"USDHKD": 4.0e6, "USDCNH": 1.5e6, "EURUSD": -2.0e6}
_JUMP_PRODUCT = "FX Target"
_JUMP_PRODUCT_SHARE = 0.90        # of each jumping pair's move
_N_DEALS = 30


def _business_days(start: date, end: date):
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


# The world exists in ABSOLUTE time: values are a function of (label, DATE),
# identical whatever window a query asks for. (A bridged run exposed the
# original per-window construction: a one-day explain of the jump saw a
# DIFFERENT world than the month view and failed its reconciliation.)
WORLD_TODAY = date(2026, 7, 6)
JUMP_DATE = _business_days(WORLD_TODAY - timedelta(days=10), WORLD_TODAY)[-3]
WORLD_START = date(2026, 1, 5)


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

    # -- the world: factored components --------------------------------------
    def _crc_rng(self, *parts):
        return np.random.default_rng(
            zlib.crc32("|".join([*map(str, parts), str(self.seed)]).encode()))

    def _base_book(self, node, measure) -> dict:
        rng = self._crc_rng(node, measure)
        mags = rng.uniform(0.2e6, 4e6, size=len(_PAIRS))
        signs = rng.choice([1, 1, 1, -1], size=len(_PAIRS))
        return dict(zip(_PAIRS, mags * signs))

    def _weights(self, node, measure, kind, labels) -> dict:
        """One dirichlet marginal per dimension — the PROPORTIONAL factor."""
        rng = self._crc_rng(node, measure, kind)
        return dict(zip(labels, rng.dirichlet(np.ones(len(labels)))))

    def _jump_product_weights(self) -> dict:
        """The jump's CONCENTRATED product distribution (same for all jumping
        pairs): 90% FX Target, the rest spread evenly."""
        rest = (1.0 - _JUMP_PRODUCT_SHARE) / (len(_PRODUCTS) - 1)
        return {p: _JUMP_PRODUCT_SHARE if p == _JUMP_PRODUCT else rest
                for p in _PRODUCTS}

    def _pair_components(self, node, measure, days):
        """(base[u] array over days WITHOUT jump, jump[u] array over days).
        Anchored at WORLD_START — window-independent absolute time."""
        base_levels = self._base_book(node, measure)
        calendar = _business_days(WORLD_START, max(days[-1], WORLD_TODAY))
        index = {d: i for i, d in enumerate(calendar)}
        base, jump = {}, {}
        for label, level in base_levels.items():
            walk_rng = self._crc_rng(node, measure, label)
            walk = walk_rng.normal(0, abs(level) * 0.01, size=len(calendar)).cumsum()
            base[label] = np.array([level + walk[index[d]] for d in days])
            jump[label] = np.array([_JUMPS.get(label, 0.0) if d >= JUMP_DATE else 0.0
                                    for d in days])
        return base, jump

    # -- slicing: filters cut the SAME cells whatever the grouping ------------
    def _parse_slices(self, filters):
        """Filter values match whichever dimension pool contains them —
        cross-cuts ('by underlying, filtered to FX Target') slice the world."""
        slices = {"u": set(_PAIRS), "p": set(_PRODUCTS), "b": set(_BOOKS)}
        pools = {"u": _PAIRS, "p": _PRODUCTS, "b": _BOOKS}
        for dim in slices:
            matched = set()
            for f in filters:
                matched |= {l for l in pools[dim] if f.lower() in l.lower()}
            if matched:
                slices[dim] = matched
        return slices

    def _grouped_values(self, node, measure, days, row_code, filters):
        """(labels, values[label] -> array over days) for any grouping of the
        sliced cell world. Marginals: underlying/product/book are exact;
        currency/unknown dims are proportional reallocations of the sliced
        total (correctly uninformative); deals partition the sliced cells."""
        base, jump = self._pair_components(node, measure, days)
        w_prod = self._weights(node, measure, "prod", _PRODUCTS)
        w_book = self._weights(node, measure, "book", _BOOKS)
        jp = self._jump_product_weights()
        s = self._parse_slices(filters)
        U, P, B = sorted(s["u"], key=_PAIRS.index), s["p"], s["b"]
        sp = sum(w_prod[p] for p in P)
        sb = sum(w_book[b] for b in B)
        jp_P = sum(jp[p] for p in P)
        code = row_code.lower()

        base_slice = {u: base[u] * sp * sb for u in U}
        jump_slice = {u: jump[u] * jp_P * sb for u in U}
        total = np.sum([base_slice[u] + jump_slice[u] for u in U], axis=0)

        if "risktype" in code:
            # A single-measure view grouped by risk type is ONE row (the
            # measure itself) on live MRX — 8 phantom groups here sent the
            # model analyzing noise (bridge-audit finding).
            return [measure], {measure: total}
        if "underlying" in code:
            return list(U), {u: base_slice[u] + jump_slice[u] for u in U}
        if "prdinl" in code or "deal" in code.replace("rowgrp", ""):
            return self._deal_values(base, jump, w_prod, w_book, jp, U, P, B)
        # real MRX code stems: RowGrpPrdDsc/PrdTyp/PrdFamName = product axes
        if any(k in code for k in ("prddsc", "prdtyp", "prdfam", "product")):
            base_sum = np.sum([base[u] for u in U], axis=0)
            jump_sum = {p: np.sum([jump[u] for u in U], axis=0) * jp[p] for p in P}
            return sorted(P, key=_PRODUCTS.index), {
                p: base_sum * w_prod[p] * sb + jump_sum[p] * sb
                for p in sorted(P, key=_PRODUCTS.index)}
        # RowGrpPtfCod/CritBookCode/desk codes = org axes, all book-backed
        if any(k in code for k in ("book", "ptf", "folio", "desk", "cpty",
                                   "counterparty")):
            per_book_core = np.sum([base[u] * sp + jump[u] * jp_P for u in U], axis=0)
            return sorted(B, key=_BOOKS.index), {
                b: per_book_core * w_book[b] for b in sorted(B, key=_BOOKS.index)}
        if "currency" in code:
            labels = _CCYS
        else:
            labels = [f"{row_code}_{i}" for i in range(1, 9)]
        w = self._crc_rng(row_code).dirichlet(np.ones(len(labels)))
        return labels, {l: total * wi for l, wi in zip(labels, w)}

    def _deal_values(self, base, jump, w_prod, w_book, jp, U, P, B):
        """Deals PARTITION the cells (every cell belongs to one deal), so a
        deal cut reconciles to its slice's total by construction. The story
        cells (USDHKD x FX Target) concentrate in the first three deals."""
        rng = np.random.default_rng(7)
        deal_labels = []
        for i in range(_N_DEALS):
            mat = date(2026, 1, 1) + timedelta(days=int(rng.integers(30, 900)))
            deal_labels.append(f"FXO-{1800000 + i * 137}/1 | FXO STND "
                               f"{'Put' if i % 2 else 'Call'} {mat.isoformat()}")
        values = {}
        assign_rng = self._crc_rng("deal-assignment")
        assignment = {}  # (u, p, b) -> deal index
        for u in _PAIRS:
            for p in _PRODUCTS:
                for b_i, b in enumerate(_BOOKS):
                    if u == "USDHKD" and p == _JUMP_PRODUCT:
                        assignment[(u, p, b)] = b_i % 3          # deals 0-2: the story
                    else:
                        assignment[(u, p, b)] = int(assign_rng.integers(3, _N_DEALS))
        for (u, p, b), deal_idx in assignment.items():
            if u not in U or p not in P or b not in B:
                continue
            cell = base[u] * w_prod[p] * w_book[b] + jump[u] * jp[p] * w_book[b]
            label = deal_labels[deal_idx]
            values[label] = values.get(label, 0) + cell
        labels = [l for l in deal_labels if l in values]
        return labels, values

    # -- ground truth ----------------------------------------------------------
    def truth(self, node: str, measure: str, end: date = WORLD_TODAY,
              start: date = WORLD_TODAY) -> dict:
        """The planted story — ABSOLUTE, window-independent ground truth."""
        base = self._base_book(node, measure)
        return {
            "jump_date": JUMP_DATE.isoformat(),
            "jump_driver": "USDHKD",            # builds NEW positions
            "jump_second": "USDCNH",
            "jump_offset": "EURUSD",
            "explain_split": {"New": 0.70, "Passive": 0.35, "Expired": -0.05},
            "base_total": float(sum(base.values())),
            # The sweep's ground truth: where a multi-dimension diagnosis
            # must find the move concentrated vs proportional.
            "informative_dimensions": {
                "underlying": {"label": "USDHKD",
                               "jump_share": _JUMPS["USDHKD"] / sum(abs(v) for v in _JUMPS.values())},
                "product": {"label": _JUMP_PRODUCT, "jump_share": _JUMP_PRODUCT_SHARE},
            },
            "diffuse_dimensions": ["book", "portfolio", "desk", "currency",
                                   "counterparty"],
        }

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

        if "riskexpain" in row_code.lower():
            _, values = self._grouped_values(node, measure, days,
                                             "RowGrpRiskType", filters)
            total = next(iter(values.values()))
            return self._explain_frame(measure, total)

        labels, values = self._grouped_values(node, measure, days, row_code, filters)

        if "history" in col_form.lower():
            return self._history_frame(labels, values, days)
        if "Difference" in col_sel or "Previous" in col_sel:
            return self._compare_frame(labels, values, days)
        return self._snapshot_frame(labels, values)

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

    def _explain_frame(self, measure, total):
        """Risk Explain compare over the SLICED total: New/Passive/Expired
        reconciling to the slice's move (filters slice the same world)."""
        total_start, total_end = float(total[0]), float(total[-1])
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
