---
name: answer_standard
when_to_use: Designing the answer's blueprint, writing the final output, and checking it — what a complete answer IS and how it reads, per response mode.
examples:
  - "Analyse the variation of FX Vega on GFXOPEMK" -> analysis note, 3-4 sections
  - "Extract the portfolio list under GFXOPEMK" -> the complete table + one line
  - "Plot EQ PV Diff across spot shifts" -> the chart + a caption
---

# The answer standard — derive THIS question's bar, then deliver it

Never a template: derive the bar fresh from the mode and the principles below.
The Blueprint is the per-question contract; this file is how to derive and
honor it.

## First: pick the RESPONSE MODE (the size and shape of the answer)

- **ANALYSIS NOTE** — "analyse / explain / what drove / compare over time".
  3-4 sections, each 1-2 sentences over its artifact. Exec summary first.
- **EXTRACTION** — "extract / list / give me the table of". The COMPLETE
  table IS the answer: one lead-in line (scope, as-of COB, row count), then
  the full table in one section. No exec summary, no analysis sections, no
  row cap — completeness is the quality bar here.
- **PLOT** — "plot / chart / show the evolution of". The chart IS the answer:
  one caption line (what, window, units), correct axes, nothing else unless
  the data reveals something the user must know (one sentence max).
- **FACT LOOKUP** — "what is / which / how much". 1-2 sentences + the number
  or a mini-table (top row(s) only). Two sentences is a COMPLETE answer.
- **MRX META** — questions about MRX itself (views, risk types, parameters,
  which data feeds what). Answer from the MRX knowledge (menu/manuals), cite
  what is documented, and say plainly when something is not documented —
  never guess codes or mechanics.

## The analysis principles (they bind ANALYSIS NOTES; lighter modes take only
what applies)

1. QUANTIFY AND RECONCILE — headline numbers stated, parts visibly adding to
   the net: "+12.6m gross positive vs -6.9m offsets = +5.7m net". An offset
   has a negative share and is called an offset.
2. DATE WHAT HAPPENED — when time is involved the path matters: "trough 5.7m
   on 06-18, largest daily move +6.09m on 07-02", never just an endpoint
   difference. Say when the end-to-end number hides a round-trip.
3. DECOMPOSE THE WHY — prefer MRX-native Risk Explain (New / Passive /
   Expired components) over inferring: "New +5.53m explains ~96% of the net"
   is a fact; "traders bought vol" is a story. State which KIND of change it
   was: new positions vs expiries vs revaluation of existing book.
4. CONCENTRATION when it is the story — one name vs broad: give BOTH
   denominators explicitly ("74% of the NET move; 21.7% of GROSS movement";
   "top-5 = 51% of gross"), they answer different questions.
5. CONTEXT is one line, not a section — the COB window and units-as-reported
   (MRX applies no currency conversion), limit headroom ONLY when a limit is
   recorded in the desk context. Standard instrument knowledge is allowed
   when LABELLED: "context: USDHKD is a managed-band pair, so vega there is
   band-stress exposure" — never asserted as the cause of the move.
6. CLAIM NOTHING THE NUMBERS DON'T SUPPORT — and claim EVERYTHING they do:
   paired offsetting legs, new-position builds, and one-name concentration
   are derivable facts whose omission makes a note incomplete.
7. BREVITY IS QUALITY — 1-2 sentences per section; analysis tables show the
   ~8 rows that carry the story (extraction tables are complete, see modes);
   never restate a number the summary already gave. A note that could be a
   third shorter without losing a decision-relevant fact is too long.

## Writing mechanics (all modes)

- Exec summary (analysis notes): 2-3 sentences — net move, dominant driver +
  main offset, the verdict — then `## <section>` headings in blueprint order.
- Numbers: thousands separators; sign conventions in words ("less negative",
  "an offset"); percentages say their denominator (of net / of gross).
- Charts/tables render UNDER your text: interpret them, never re-list them.
  HARD RULE: never write a markdown table (|...|) in the note for data
  attached via section() — it would appear TWICE on screen. One interpreting
  sentence; the attached table renders below it.
- A section whose data is genuinely unavailable after trying gets ONE honest
  sentence about what is missing — not a paragraph of hedging.

## When the driver dimension is unknown: THE SWEEP (mode: "sweep")

"Explain/analyse the variation" with no dimension named is answered by
INVESTIGATION, not by one blind breakdown:

1. SWEEP: two-COB COMPARE fetches (never history) across the candidate
   dimensions — product, portfolio, underlying, counterparty, book/desk (see
   the capability menu; deals are a DRILL, never a sweep). Request them ALL
   IN ONE message so they run in parallel; one slow dimension must not
   serialize the rest. A dimension returning an error or Invalid Parameters
   is dropped after one retry and noted in one line.
2. DIAGNOSE: run `helpers.ops.sweep_diagnostics({"product": df, ...})`
   IMMEDIATELY and reason from its ONE ranked table — do not re-read six
   frames row by row. The decisive metric is DIVERGENCE (the move's
   distribution vs the book's distribution): divergence >= ~0.3 with a
   dominant top-1 = the story dimension; divergence near 0 = the dimension
   moves PROPORTIONALLY — one sentence ("broad-based across portfolios"),
   never a drill, whatever its top-1 share of the move.
3. RECONCILE: every dimension's leaf sum must equal the same net move — the
   diagnostics table flags failures (`reconciled`); a non-reconciling cut is
   QUARANTINED from conclusions, said in one line. Never use server-side
   movers filters in sweep cuts — dropped rows break the sum.
4. DRILL the informative dimension(s) only: filtered Risk Explain, the deal
   drill on the top mover, cross-cuts (e.g. by underlying filtered to the
   top product). Cross-cuts LOCATE, they never ADD — reconcile a cross-tab
   back to the single-dimension cut it drills. When several dimensions
   concentrate on the same positions, that is ONE story with coordinates
   ("USDHKD FX Targets in FXO_EM_ASIA"), not several findings.
5. WRITE: the blueprint gives the sweep a VISIBLE section (e.g. "Where the
   move lives") whose artifact is the ranked diagnostics table — the reader
   sees why the drill went where it went. When |net| < ~20% of gross, shares
   of net are meaningless: lead with gross and the offsetting legs.

If the question names the dimension, or the scope is a single pair or
portfolio, do NOT sweep — standard mode.

## Deriving the bar (the Designer's method)

Mode first. Then, for analysis notes: does time matter (-> a dated-path
section)? does "why" matter (-> a Risk Explain section)? is concentration
plausibly the story (-> both denominators)? Design ONLY the sections those
answers earn — typically 2-4 — with the window pinned ONCE (exact COB dates)
and every fetch carrying that window verbatim.

- THE FETCH BUDGET DEPENDS ON THE MODE you set on the blueprint (hard caps,
  "after:" fetches included): standard = 6 (design AT MOST 5, prefer fewer);
  sweep = 12 (the sweep dimensions + drills; the cap is HEADROOM, not a
  quota — stop the moment a dimension is decisive). Never spend the whole
  budget up front: leave room for the adaptive drill.
- The executive summary is NEVER a section — it is the unheaded text before
  the first `## heading`. Do not design an "Executive summary" section; its
  content requirements belong in the TARGET.
