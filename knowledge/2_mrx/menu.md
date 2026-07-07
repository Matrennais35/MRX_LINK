---
name: mrx_menu
when_to_use: Designing an answer — what data MRX can actually serve (the capability menu), and how to phrase fetch requests.
examples:
  - "why did FX Vega move -> Risk Explain decomposition (New/Passive/Expired), MRX-native"
  - "path over a month -> history dates form, dates across columns"
---

# MRX capability menu (multirow view)

What questions the data can answer, and how to ASK for it (fetch requests are
natural language — the fetch tool builds the URL; your job is to request the
right SHAPE). The URL mechanics live in the manuals.

## Measures (risk types) — one per view call, always exactly one
Families: EQ (Delta Cash, Gamma, Vega/Wizoo, Dividends, Repo, Smile),
FX (Delta, Vega "Soho", Gamma Multi, Vanna, Exposure/Switcher),
IR (Delta, Vega, Basis/Bond/Repo spreads, Inflation),
CR (Delta PSP, Default Risk, Vega, Base Correlation), CO (Delta, Vega).
Never combine two measures in one request — one measure, one view.

## RISK EXPLAIN — the native "why did it change" (CONFIRMED LIVE 2026-07-07)
MRX decomposes any measure's change into CAUSE COMPONENTS: **New** (positions
added), **Passive** (carry/aging of the existing book), **Expired** (risk
rolled off). Served as a breakdown (rows = explain cause, second level = risk
component), combinable with:
- the compare form (Current / Previous / Difference between two COBs),
- pair/underlying filters (e.g. only USDHKD and USDCNH),
- ANY two COB dates — including a single day (explain one dated jump).
Request phrasing that works: "FX Vega risk explain on <node>, grouped by
explain cause/component, comparing COB <start> vs <end>[, filtered to
<pairs>]". PREFER this over recomputing attribution from deal-level data —
it is authoritative and reconciles (check: components sum to the move).

## THE SWEEP — the intended first move for "why/what drove" questions
Compares are CHEAP: fetching two-COB compare breakdowns across SEVERAL
dimensions in parallel costs one round-trip and locates the story before any
drill. Confirmed sweep-worthy row groupings (pick per question — no fixed
set): Product (RowGrpPrdDsc), Product Family (CritPrdFamName), Portfolio
(RowGrpPtfCod), Underlying/pair (RowGrpUnderlying), Counterparty
(RowGrpCptyBk), Book (CritBookCode), Desk, Issuer (RowGrpIssr), Strategy
(RowGrpStrategy). Deal/Security (RowGrpPrdInlNo) is a DRILL after the driver
is named — deal-level on a whole node is heavy.

## Breakdowns (row groupings, ~360 codes) — ONE dimension per request
book, portfolio, desk, node, currency, currency-pair/underlying, product,
deal/security, tenor (option/swap), strike, maturity, issuer, guarantor,
rating, country/region, risk explain cause...
GOTCHA: nesting several ROW levels returns a Depth hierarchy with ONE label
column (deepest level only) and ancestor rows duplicating child sums. Design
SINGLE-dimension row cuts — for two dimensions use a CROSS-TAB (below).

## CROSS-TABS — the view is a PIVOT: rows x COLUMNS in one fetch
The column axis is not just Total/History. Putting a SECOND dimension across
the columns gives a clean 2D matrix (no Depth problems):
- "FX Vega by currency pair ACROSS option tenors" -> rows=pair, columns=
  option tenor: the pair x tenor matrix in ONE fetch ("which tenors explain
  the move" needs no second drill).
- Columns can also be: product, portfolio, currency, underlying, maturity,
  risk component, swap tenor.
- SCENARIO LADDERS: columns = "spot shifts" (PV/measure across the spot
  ladder — e.g. "EQ PV Diff for all spot shifts") or "vol shifts"; also
  official stress scenario columns. Ask: "<measure> on <node> with spot
  shifts across the columns, as of <COB>".

## Targeted filters (combinable; use to keep drills small)
underlying/pair, portfolio, PRODUCT family/type ("only FX Targets"),
deal/security, option/swap tenor, strike, maturity, issuer, trader,
currency, counterparty (name/rating/country/industry). Also a SERVER-SIDE
MOVERS FILTER: "only rows whose variation exceeds <threshold>" — MRX drops
the noise before sending (use for wide compare cuts on big nodes).

## UNITS — values arrive in the DISPLAY CURRENCY (default EUR)
MRX converts to a display currency (EUR unless requested otherwise). State
units as "EUR (MRX display currency)" — or request another display currency
explicitly. (Corrects the earlier "no conversion" belief.)

## Time forms — pick the shape the section needs
- SNAPSHOT: one COB. "as of the latest available COB" -> T-1 (weekends and
  holidays roll back; Monday's latest is Friday... verify: latest = previous
  business day).
- COMPARE: Current vs Previous vs Difference columns for TWO dates — the
  day-on-day / start-vs-end form. Cheap and precise for net-change sections.
- HISTORY: dates across columns for a window (~23 business days per month) —
  the ONLY form for path/trend/jump-dating sections.
PIN THE WINDOW ONCE in the blueprint (exact COB dates) and put the SAME dates
in every fetch request verbatim — independent per-request derivations drift.

## Scope, filters, cost
One node/perimeter per view (GFXOPEMK, IRUS, GLEQD...). Filters: underlying/
pair (multi-value works: "USDHKD and USDCNH"), portfolio, product family.
COST: totals and single-dimension cuts are cheap; deal-level on a whole node
is heavy (1000s of rows) — always filter deal drills to the identified
driver; a whole-node DAILY HISTORY can be slow (a live fetch once exceeded
3 minutes) — request it once, reuse thereafter (already-fetched data is free).
