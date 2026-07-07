---
name: mrx_semantics
when_to_use: Choosing measures and writing about them — what each measure MEANS and the interpretation constraints that keep a note correct.
examples:
  - "FX Vega jumped -> the book's sensitivity to implied vol moved, say what KIND of change"
  - "top 5 worst -> most negative for loss-like metrics"
---

# What the measures mean (and how to interpret them correctly)

Write like a risk analyst: name the sensitivity, not just the number. One
plain-language meaning per measure — use these words in notes.

## Equity (EQ)
- EQ Delta (Cash): first-order PV change for a spot price shift — directional
  equity exposure.
- EQ Vega: first-order sensitivity to an additive implied-volatility shift.
- EQ Gamma: second-order sensitivity to spot — how delta itself moves.
- EQ Dividends: sensitivity to a dividend-expectation shift.
- EQ Repo: sensitivity to a repo-curve shift (financing of the hedge).
- EQ Smile: sensitivity to volatility-smile convexity.

## Foreign Exchange (FX)
- FX Delta: PV change for an FX spot shift — directional currency exposure.
- FX Vega: sensitivity to FX implied-volatility shift (an options book's
  vol exposure). TODO(red-pen): document the desk's naming — e.g. what
  distinguishes the "Soho" vega variant.
- FX Gamma (Multi): second-order sensitivity to FX spot.
- FX Vanna: cross-sensitivity — how vega moves when spot moves.

## Interest Rates (IR) & Inflation
- IR Delta: sensitivity to a yield-curve shift.
- IR Vega: sensitivity to rates implied-volatility shift.
- IR Basis / Bond / Repo Spread: sensitivity to the spread between curves
  (basis), bond vs base curve, repo over OIS.
- INF ZC / Real Delta: sensitivity to zero-coupon / real-rate inflation shifts.

## Credit (CR)
- CR Delta (PSP): PV change under a CDS-spread shift.
- CR Default Risk: loss under an issuer-default assumption.
- CR Vega: sensitivity to credit volatility.
- CR Base Correlation: sensitivity to tranche base-correlation shift.

## Commodities (CO)
- CO Delta / CO Vega: spot and implied-vol sensitivities on commodities.

## Risk Explain components — the ECONOMICS
- New = risk from positions ADDED in the window (trading activity).
- Passive = the carry/aging of the EXISTING book (revaluation, time decay,
  market-data moves on unchanged positions).
- Expired = risk that ROLLED OFF (maturities, expiries, unwinds).
A note says which KIND dominated — "the increase is new positions, not
revaluation of the existing book" — never a market story the split doesn't
support.

## Interpretation constraints (violating these makes a note WRONG)
- DIFFERENT MEASURES NEVER SUM: FX Vega + EQ Delta is meaningless; never
  aggregate across measures or families. One measure per figure, always.
- TOP-N ON LOSS-LIKE METRICS = MOST NEGATIVE by default (worst first);
  say "least negative" explicitly when the user asks for the other end.
- SIGNS ARE MEANING: negative vega = short vol; state long/short in words,
  and "less negative" is not "smaller".
- Units are as-reported by MRX (no currency conversion exists) — state the
  reported unit; never convert or imply a currency.
- Standard instrument knowledge is allowed only LABELLED as context
  ("context: USDHKD is a managed-band pair...") — never asserted as the
  cause of a move the data doesn't establish.
