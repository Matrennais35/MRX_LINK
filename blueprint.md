# Designer review — 14 blueprints (20260707_135150)

Judge each: right response mode? right sections/bar? right fetches (shape + window pinned)? clarification only when truly warranted?


---

## Q1 (61s): Analyse the variation of FX Vega on GFXOPEMK over the last month.

```
TARGET: Explain how FX Vega on GFXOPEMK changed over the trailing month ending at the latest available COB, including the net move, the dated path, the main pair/underlying contributors and offsets, and whether the move was driven by new positions, passive revaluation/aging, or expiries.

SECTIONS:
1. [Executive summary] must establish: State the data context once: trailing month using COB 2026-06-08 to COB 2026-07-06, units as reported by MRX with no currency conversion. Summarise the start level, latest level, net change, dominant contributor, main offset, and whether the move looks concentrated or broad-based.
   data: Daily total history, pair/underlying compare, and MRX risk explain for the same COB window. | shown as: none
2. [Path and timing] must establish: Show how the total FX Vega evolved through the month: start, end, net change, peak, trough, largest daily up/down moves, and whether the endpoint move hides a round-trip.
   data: Daily total FX Vega history on GFXOPEMK from COB 2026-06-08 through COB 2026-07-06. | shown as: line chart
3. [Pair/underlying drivers] must establish: Reconcile the net move to the main currency-pair/underlying contributors, explicitly separating positive drivers from negative offsets. Show top contributors with both share of net move and share of gross absolute movement to judge concentration.
   data: FX Vega compare by currency-pair/underlying on GFXOPEMK between COB 2026-06-08 and COB 2026-07-06. | shown as: ranked bar + table
4. [Risk-explain decomposition] must establish: Use MRX-native Risk Explain to decompose the total FX Vega change into New, Passive, and Expired components, with components adding back to the net move. Classify the variation as mainly new-position build, expiry roll-off, or passive movement; do not infer trader intent beyond the explain data.
   data: FX Vega Risk Explain on GFXOPEMK grouped by explain cause/component, comparing COB 2026-06-08 vs COB 2026-07-06. | shown as: waterfall

FETCHES:
- (now) Daily total FX Vega on GFXOPEMK, history dates, COB 2026-06-08 through COB 2026-07-06, units as reported.
- (now) FX Vega on GFXOPEMK by currency-pair/underlying, compare COB 2026-06-08 vs COB 2026-07-06, showing Current, Previous, and Difference.
- (now) FX Vega risk explain on GFXOPEMK, grouped by explain cause/component, comparing COB 2026-06-08 vs COB 2026-07-06.
```

---

## Q2 (10s): Which currency pair drove the increase since mid-month, and is the move concentrated or offsetting?

```
CLARIFICATION NEEDED: Which MRX node/perimeter, risk measure, and mid-month start COB should I use for the currency-pair move analysis?
```

---

## Q3 (5s): Drill into the top pair: which tenors and deals explain its move?

```
CLARIFICATION NEEDED: Which node, risk measure, and COB comparison/window should I use to identify the “top pair” and drill its tenors and deals?
```

---

## Q4 (4s): Summarise what we've found so far in this conversation.

```
TARGET: Confirm whether there are any prior findings to recap in this conversation; since this is the first question and no data has been fetched, the answer should state that there are no findings yet.

SECTIONS:
1. [Conversation summary] must establish: There are no prior questions, analyses, fetched MRX data, or conclusions in this conversation to summarise yet.
   data: Conversation history supplied by the user: marked as the first question, with no reusable data available. | shown as: none

FETCHES:
```

---

## Q5 (11s): Show IR Delta on IRUS by desk for the latest COB, compared with T-1.

```
TARGET: Provide the desk-level IR Delta breakdown for IRUS at the latest available COB, with the immediately preceding business COB and the desk-by-desk change shown side by side.

SECTIONS:
1. [IR Delta by desk — latest COB vs prior COB] must establish: A complete desk breakdown of IRUS IR Delta with Current, Previous, and Difference columns, using MRX units as reported; scope and COB dates stated in the lead-in.
   data: Compare view for IR Delta on node IRUS, grouped by desk, latest available COB versus the prior business COB. | shown as: table

FETCHES:
- (now) IR Delta on IRUS, grouped by desk, compare latest available COB versus the immediately preceding business COB
```

---

## Q6 (9s): Plot the evolution of the total IR Delta on IRUS over the last two weeks.

```
TARGET: Visualize the recent path of IRUS total IR Delta over the trailing two-week window ending at the latest available COB, so the user can see direction, volatility, and any notable jumps.

SECTIONS:
1. [IRUS total IR Delta evolution] must establish: A line chart of daily total IR Delta for IRUS across the trailing two-week COB window, with dates on the x-axis and IR Delta units as reported by MRX on the y-axis; caption states the exact COB window and that latest means T-1.
   data: Daily total IR Delta history for node IRUS from COB 2026-06-23 through COB 2026-07-06, using MRX units as reported. | shown as: line chart

FETCHES:
- (now) daily total IR Delta on IRUS, history dates, COB 2026-06-23 through COB 2026-07-06
```

---

## Q7 (7s): What is the biggest single-desk IR Delta change vs T-1, in absolute terms?

```
CLARIFICATION NEEDED: Which MRX node/perimeter should I search for the single-desk IR Delta change (e.g., IRUS or another IR/global node)?
```

---

## Q8 (4s): What is the total EQ Delta Cash for US_SPX in GLEQD as of the latest COB?

```
TARGET: Provide the latest available COB total EQ Delta Cash exposure for the US_SPX underlying within GLEQD.

SECTIONS:
1. [Latest total] must establish: The single total EQ Delta Cash value for GLEQD filtered to US_SPX, as of the latest available COB, with units as reported by MRX and no unsupported interpretation.
   data: Snapshot total EQ Delta Cash on GLEQD filtered to underlying US_SPX for the latest available COB. | shown as: none

FETCHES:
- (now) total EQ Delta Cash on GLEQD, filtered to underlying US_SPX, as of the latest available COB
```

---

## Q9 (15s): What does FX Vega measure, and why might it jump at month-end?

```
TARGET: Give the analyst a concise MRX/market-risk explanation of what FX Vega represents and the plausible, non-speculative reasons it can move sharply at month-end, including how an actual jump would be validated in MRX.

SECTIONS:
1. [FX Vega measure] must establish: Define FX Vega as the FX option book’s sensitivity to implied volatility moves, note that MRX carries it as the FX Vega/Soho risk type, and state that units/sign conventions are as reported by MRX unless desk conventions specify otherwise.
   data: MRX documented risk-type taxonomy plus standard market-risk definition of vega. | shown as: none
2. [Month-end jump mechanisms] must establish: Explain the main month-end mechanisms without over-claiming: new month-end trades/hedges, expiries rolling off, passive aging/tenor-bucket migration, and revaluation from implied-vol surface moves; distinguish position-change effects from passive/expired effects.
   data: MRX Risk Explain capability documentation: New, Passive, Expired components; standard option-risk behavior around aging and tenor buckets. | shown as: none
3. [How to verify an actual jump] must establish: State that for a named node/date the correct validation is FX Vega history to date the jump, then FX Vega Risk Explain between the relevant COBs to decompose it into New, Passive, and Expired components; no conclusion about a specific jump should be made without that data.
   data: MRX capability documentation for FX Vega history and FX Vega Risk Explain compare form. | shown as: none

FETCHES:
```

---

## Q10 (53s): Analyse GFXOPEMK.

```
TARGET: Give the analyst a default market-risk review of the whole GFXOPEMK node: current main FX risk levels, what changed over the latest trailing month, when the material move happened, what MRX Risk Explain says caused it, and whether the move is concentrated in specific currency pairs. Use latest available COB by default: COB 2026-07-06; trailing month window: COB 2026-06-05 to COB 2026-07-06; units as reported by MRX with no currency conversion.

SECTIONS:
1. [Executive summary] must establish: In 2-3 sentences, state the material one-month net change(s) across GFXOPEMK's main FX measures, the dominant measure and main offset if any, the main Risk Explain cause once known, and a verdict on whether the move is broad or concentrated. Include the data context once: COB 2026-06-05 to COB 2026-07-06, latest COB 2026-07-06, units as reported.
   data: All fetched totals, history, risk explain, and pair breakdowns. | shown as: none
2. [Current profile and one-month change] must establish: Show the current level and start-to-latest change for GFXOPEMK's main FX measures, identifying the dominant current exposure and the largest absolute mover; reconcile signs clearly, including offsets where a measure moved opposite the overall story.
   data: Compare totals for FX Delta, FX Vega, FX Gamma Multi, FX Vanna, and FX Exposure/Switcher on GFXOPEMK between COB 2026-06-05 and COB 2026-07-06. | shown as: table
3. [Path of the dominant move] must establish: For the dominant moving measure identified in the profile, date the path: start, end, peak/trough, largest daily rise/fall, and whether the endpoint move hides a round-trip.
   data: Daily history for the dominant moving measure on GFXOPEMK from COB 2026-06-05 to COB 2026-07-06. | shown as: line chart
4. [Why it changed] must establish: Use MRX Risk Explain to decompose the dominant measure's change into New, Passive, and Expired components; components must sum to the net move and the section must state which kind of change dominated: new positions, revaluation/carry of existing book, or expiries.
   data: Risk Explain for the dominant moving measure on GFXOPEMK, grouped by explain cause/component, comparing COB 2026-06-05 vs COB 2026-07-06. | shown as: waterfall
5. [Where the move is concentrated] must establish: Rank currency pairs/underlyings by contribution to the dominant measure's one-month change, showing both net-share and gross-movement share for the top contributors and offsets; conclude whether the move is one-name/pair-driven or broad.
   data: Currency-pair/underlying breakdown for the dominant moving measure on GFXOPEMK, compare COB 2026-06-05 vs COB 2026-07-06. | shown as: ranked bar + table

FETCHES:
- (now) Total FX Delta on GFXOPEMK, compare COB 2026-06-05 vs COB 2026-07-06, columns Current, Previous, Difference.
- (now) Total FX Vega (Soho) on GFXOPEMK, compare COB 2026-06-05 vs COB 2026-07-06, columns Current, Previous, Difference.
- (now) Total FX Gamma Multi on GFXOPEMK, compare COB 2026-06-05 vs COB 2026-07-06, columns Current, Previous, Difference.
- (now) Total FX Vanna on GFXOPEMK, compare COB 2026-06-05 vs COB 2026-07-06, columns Current, Previous, Difference.
- (now) Total FX Exposure/Switcher on GFXOPEMK, compare COB 2026-06-05 vs COB 2026-07-06, columns Current, Previous, Difference.
- (after: Current profile and one-month change) Daily total <dominant moving FX measure from 'Current profile and one-month change'> on GFXOPEMK, history dates COB 2026-06-05 to COB 2026-07-06.
- (after: Current profile and one-month change) <Dominant moving FX measure from 'Current profile and one-month change'> risk explain on GFXOPEMK, grouped by explain cause/component, comparing COB 2026-06-05 vs COB 2026-07-06.
- (after: Current profile and one-month change) <Dominant moving FX measure from 'Current profile and one-month change'> on GFXOPEMK, breakdown by currency-pair/underlying, compare COB 2026-06-05 vs COB 2026-07-06, columns Current, Previous, Difference.
```

---

## Q11 (10s): What MRX files are used for FX Gamma?

```
TARGET: Identify the documented MRX file/feed lineage for the FX Gamma risk type so the analyst can trace or troubleshoot the measure, without pulling risk data.

SECTIONS:
1. [FX Gamma MRX files] must establish: List the file/feed names documented as used for FX Gamma, with a short purpose/role for each; if the MRX documentation does not specify file names for FX Gamma, say that plainly and avoid guessing.
   data: MRX metadata/manuals covering FX risk-type inputs or file mappings for FX Gamma; no COB risk view is needed. | shown as: table

FETCHES:
```

---

## Q12 (12s): Extract the portfolio list under GFXOPEMK.

```
TARGET: Provide the complete set of portfolios currently represented under the GFXOPEMK node, using the latest available COB and the node’s default/main FX-options risk view.

SECTIONS:
1. [Portfolio list] must establish: A complete extraction table of portfolio rows under GFXOPEMK as of the latest available COB; include the portfolio identifier/name and the reported risk value used to evidence presence, with row count in the lead-in.
   data: Latest-COB snapshot on GFXOPEMK broken down by portfolio for the node’s main FX-options measure. | shown as: table

FETCHES:
- (now) latest available COB snapshot of FX Vega (Soho) on GFXOPEMK, broken down by portfolio; include all portfolio rows
```

---

## Q13 (11s): What is the main underlying of the FX Targets products in GFXOPEMK?

```
TARGET: Identify the dominant currency pair/underlying for FX Targets in GFXOPEMK, using the latest available COB and a clear risk-based ranking so the analyst can see the top name and its dominance.

SECTIONS:
1. [Main underlying] must establish: The top underlying for FX Targets in GFXOPEMK, ranked by absolute FX Vega, with its signed Vega amount and share of total absolute FX Vega; show the next few underlyings only if needed to validate that it is clearly the main one.
   data: Latest-COB snapshot of FX Vega on GFXOPEMK, filtered to product = FX Targets, grouped by currency-pair/underlying. | shown as: mini-table

FETCHES:
- (now) Latest available COB snapshot of FX Vega on GFXOPEMK, filtered to product FX Targets, grouped by currency-pair/underlying; include totals and rank by absolute FX Vega descending.
```

---

## Q14 (10s): Plot the EQ PV Diff for all spot shifts as of yesterday.

```
CLARIFICATION NEEDED: Which node/perimeter should I use for the EQ PV Diff plot?
```