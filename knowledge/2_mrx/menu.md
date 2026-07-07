---
name: mrx_menu
when_to_use: Designing an answer — what data MRX can actually serve (the capability menu).
examples:
  - "Can MRX give a daily history of a measure? (yes — history dates)"
  - "Can MRX decompose a change into causes? (yes — explain-type risk types)"
---

# MRX capability menu (multirow view)

What questions the data can answer. The URL mechanics live in the manuals —
this is the DESIGNER's menu.

## Measures (risk types)
One measure per view call (p13 is mandatory, exactly ONE code). Families:
EQ (delta cash, gamma, vega/wizoo, dividends, repo, smile), FX (delta, vega
"Soho", gamma multi, vanna, exposure/switcher), IR (delta, vega, basis/bond/
repo spreads, inflation), CR (delta PSP, default risk, vega, base correlation),
CO (delta, vega). Explain-type risk types exist (e.g. "Risk Explain") that
decompose a CHANGE into its causes — prefer them for "why did X move"
questions over recomputing attribution from deal data. (Exact codes: manuals.)

## Breakdowns (row groupings, ~360 codes)
Any ONE dimension per level: book, portfolio, desk, node, currency,
currency-pair/underlying, product, deal/security, tenor (option/swap), strike,
maturity, issuer, guarantor, rating, country/region...
GOTCHA: nesting multiple levels returns a Depth hierarchy with ONE label
column (deepest level only) and ancestor rows that duplicate child sums —
DESIGN SINGLE-DIMENSION CUTS (several simple views beat one nested view).

## Time forms
- SNAPSHOT: one COB date (latest = T-1).
- COMPARE: Current vs Previous vs Difference columns for two dates (the
  day-on-day / period-end view).
- HISTORY: dates across columns (wide frame) for a window — the form for any
  path/trend/evolution question. ~23 business days per month.

## Scope & filters
A node/perimeter per view (e.g. GFXOPEMK, IRUS); filters on underlying/pair
(e.g. p17=USDHKD), portfolio, product... A filtered deal-level view of ONE
underlying is cheap; an unfiltered deal-level view of a whole node is heavy
(thousands of rows) — filter drills to the identified driver.

## Granularity & cost
Every fetch is a slow, budgeted call into a production system. Totals and
by-dimension cuts are cheap; deal-level is the expensive drill — design it
targeted (after the driver is known), never speculative.
