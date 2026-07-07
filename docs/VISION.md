# MRX Analyst — Vision

*The stable reference this project is tested against. Every architecture or
feature decision must answer: which part of this document does it serve, and
is it the simplest thing that serves it?*

## The problem, in one sentence

> **A user asks a market-risk question in natural language → decide what they
> want and what the output should look like given what MRX can serve →
> parameterize the right view URL(s) → download the dataframe(s) → perform the
> data analysis → answer as a structured desk note.**

## The central insight

**The pivotal act of intelligence is ONE joint decision: given what the user
wants AND what MRX can actually serve, what should the output look like?**
Everything else — URL building, downloading, pandas, prose — is execution of
that decision.

Every earlier architecture buried this decision: the 5-stage pipeline split it
between a Planner that didn't know MRX's capabilities and a DataScout that
knew MRX but wasn't designing the answer; a pure agent loop dissolves it into
implicit step-by-step reasoning. The live eval proved the point: plan quality
was excellent *in a vacuum* — every planning failure was capability-blindness
(designing cuts MRX returns as hierarchy junk; never planning categorized
drivers because nothing knew Risk Explain exists).

## The architecture: DESIGN → EXECUTE → WRITE

### 1. The Answer Designer — the step that matters most

One reasoning act holding three things: the question (intent), the **MRX
capability MENU**, and the **gold standard**. It produces the **ANSWER
BLUEPRINT** — a mock of the final note, each element tied to the data that
feeds it:

```
"Analyse the variation of FX Vega on GFXOPEMK over the last month"
  §1 Exec summary — net move, %, dominant driver + offset      ← from A, B
  §2 The path — daily line + dated-jumps table                 ← A: multirow, total, history dates
  §3 Drivers — signed ranked bar + table by pair               ← B: multirow, by-underlying
  §4 What's underneath — drivers categorized new/expiry/market ← C: multirow with an
                                                                 explain-type risk type
                                                                 (e.g. Risk Explain) — the
                                                                 menu says MRX serves
                                                                 change-attribution natively
  §5 Concentration & context                                   ← from B/C
  Plan: fetch A,B now; C targeted after §3 names the top pair.
  Ambiguity check: none — proceed (else: ask the user back instead).
```

The blueprint is user-visible ("here is what I will build for you"), it is the
Executor's checklist, the Critic's rubric, and the eval's scoring target.

### 2. The Executor — an adaptive loop filling the blueprint

The Claude-Code-style tool loop (hard step cap in plain code), with the
blueprint as its checklist:

- `fetch_mrx("<data needed, in NL>")` — the MRX-expertise tool. Inside it: the
  URL MANUALS (view selection, parameters, tables, COB rules), deterministic
  validation, the HARD fetch budget, zero-cost reuse from the catalog,
  deterministic profiling. The big MRX knowledge never enters the main context.
- `run_python(code)` — free pandas/matplotlib in a persistent per-question
  namespace: fetched frames by name, tested `helpers` (leaf-aware math, trend,
  position_change, chart builders — available, never mandated),
  `section(title, table=, chart=)` attaching artifacts to blueprint slots.

When the data disagrees with the design, the Executor may trigger ONE bounded
redesign (the builder returns to the architect). Unfilled blueprint slots are
VISIBLE gaps with reasons — never silent drops.

Long conversations are summarized past a token threshold (older turns
condensed, recent kept verbatim). Later latency option, same interface:
recurring requests can become "frozen fast-paths" inside `fetch_mrx`
(pre-parameterized URLs that skip the nested builder call).

### 3. The Writer + Critic

The note is written to the blueprint (top-down desk-note method); the Critic
makes ONE anchored check — note vs blueprint vs computed artifacts — and its
findings re-enter the Executor (which can actually compute what's missing);
one bounded refine, then ship. The message history is the audit trail.

Safety is plain code inside the tools — fetch budget, URL validation, step
cap, trace. No model and no framework ever holds a gate.

## The knowledge layer (markdown — the product; each file independently improvable)

Every knowledge file uses a SKILL-FILE format (imported from LLM_CCR OG):
frontmatter with `name`, `when_to_use`, `examples` (routing metadata) + the
markdown content. Today ALL files are assembled into the prompts by
`prompts.py`; the format makes selective/dynamic loading possible later
without rework. Capability-menu entries carry `when_to_use` + example
questions the same way.

```
knowledge/
  1_intent.md          Reading the question: the target behind the words,
                       defaults (windows, scope), when to ask back.       [Designer]
  2_mrx/
     menu.md           ★ THE CAPABILITY MENU (~1 page, designer-facing):
                       what questions the data can answer — measures ×
                       breakdowns × time-forms (snapshot / T-1 compare /
                       history) × explain categories × granularity limits
                       and gotchas ("nested cuts return hierarchy junk —
                       design single-dimension cuts"). The piece NO earlier
                       version had: the designer finally knows the menu.  [Designer]
     manuals/          URL manuals per view (multirow today) + tables +
                       COB rules. Note: capabilities like Risk Explain are
                       RISK TYPES within multirow, not separate views —
                       teaching them = adding their codes/usage here.     [fetch_mrx]
     reading.md        How to read returned frames: wide date columns,
                       Depth hierarchies, Total rows, error frames,
                       deal-label conventions, units.                     [Executor]
  3_gold_standard.md   ★ PRINCIPLES of a complete risk answer + the METHOD
                       to derive THIS question's bar — never a template or
                       a catalog of question types (analysts ask too many
                       different questions for any taxonomy to hold).
                       Principles: quantify and reconcile to the net; date
                       what happened when time is involved; decompose the
                       why as far as the data allows; state concentration
                       when it's the story; units + COB; claim nothing the
                       numbers don't support; match the answer's size to
                       the question's. The Designer INSTANTIATES these into
                       each question's Blueprint — the per-question
                       contract, derived fresh. Owned and red-penned by
                       the user.                          [Designer + Critic + eval]
  4_note.md            Writing method: desk-note anatomy, tone, derivable-
                       insight-required / invented-causality-forbidden,
                       labelled context, reported units.                  [Writer]
  desk.md              The user's desk context: limits, conventions,
                       nicknames (empty template until filled).           [Designer + Writer]
  BACKLOG.md           Harvested knowledge gaps (see the learning loop).
```

## The diagnosis rule (the falsifiable maintenance contract)

Every failure — a 👎, an eval miss, a Critic finding — must map to **exactly
one** home:

- misread the target / bad output design → `1_intent.md` or `2_mrx/menu.md`
  (was it intent, or menu-blindness? the blueprint makes this visible)
- wrong view / bad URL / wrong window → `2_mrx/manuals/`
- mangled frame handling, double counts → `2_mrx/reading.md` (+ helpers if deterministic)
- unfulfilled blueprint (missing computation) → execution problem (harness/
  helpers); fulfilled-but-unsatisfying blueprint (bar set wrong) →
  `3_gold_standard.md` principles or `2_mrx/menu.md`
- right facts, unsatisfying note → `4_note.md`
- wrong desk convention/units/limits → `desk.md`

If a failure maps to none or several, the SPLIT is wrong — revisit this
document, not just the code.

## The learning loop

1. Gate rejections, fetch failures, and Critic findings are harvested into
   `knowledge/BACKLOG.md` as candidate knowledge edits (deliberate, reviewed —
   no auto-learning).
2. `eval_run.py`'s 10-question battery is the regression harness: every
   knowledge edit is proven by a re-run, diffed against the previous report.
   Two levels of judgment: the Critic judges each note against ITS OWN
   blueprint; the user judges the BLUEPRINTS (was the right bar derived?).
3. `feedback.txt` pairs each user verdict with the trace so failures diagnose
   to their file.

## Settled decisions (do not re-open without new evidence)

1. **Hand-rolled, no agent framework.** LangGraph (cap-semantics drift),
   smolagents ("experimental API", 2025 sandbox CVEs), PandasAI (dormant,
   py3.12-broken, CVE) — researched and rejected for a one-maintainer bank
   tool. The DABstep benchmark is topped by plain frontier-model loops.
2. **Gates in plain code inside the tools** — budget, validation, step cap,
   trace. Never model- or framework-controlled.
3. **Capability grows by teaching MRX** (`menu.md` + `manuals/`), not by
   building tools. Before adding any analysis op: does an MRX view serve it
   natively? Only generic math enters `helpers`. Typed per-family MRX tools
   (LLM_CCR's `get_equity_exposure`-style) are rejected for the same reason:
   every new cut would need a new tool — a capability ceiling. `fetch_mrx`
   stays natural-language over the full view surface.
4. **No exemplar/RAG answer-matching, no multi-agent debate, no per-question
   op schemas, no fixed multi-stage pipeline.** One explicit design act, then
   adaptive execution.
5. **Compute and prose are checked, not trusted**: the Critic verifies the
   note against the blueprint and the computed artifacts (one bounded refine).

## Comparables: LLM_CCR OG (read in depth, 2026-07)

A colleague team's CCR assistant independently converged on the same skeleton:
ONE tool-loop agent, knowledge as editable files, domain machinery inside
tools, stored/referenced tables, structured responses — validating this
vision's foundation. Two deliberate forks we keep, with evidence:
- **Analysis**: they cap it with a typed df-tool menu (`aggregate_table`,
  `pivot_table`...); we keep free code + optional tested helpers — the menu is
  the capability ceiling this project rejected, and the DABstep benchmark is
  topped by plain code loops. Their own skill docs concede the wall ("if no
  valid table reference can be produced, explain why").
- **Quality**: they have no answer-design step and no quality loop (generic
  todo-list middleware; output = "table reference + short text"); our
  Blueprint / gold-standard principles / Critic / eval battery exist precisely
  because our target output is a desk note.

Four imports adopted from them: the skill-file knowledge format
(`when_to_use`/`examples` routing metadata), dynamic knowledge loading as the
scaling path when domains multiply, their knowledge-document writing style
(vocabulary, interpretation rules, worked workflows — the template for
`menu.md`/`reading.md`), and long-thread summarization.

## What exists and is kept (the assets)

Views layer (multirow manual/tables → `2_mrx/manuals/`), gated fetch with
reuse + budget (`tools/mrx_fetch.py`), deterministic profiler (wide-date +
Depth-aware), sandbox executor, tested helpers (`ops.py`, `charts.py`),
catalog (datasets/turns/steps/charts), Answer/Section shapes + renderer,
feedback capture, eval harness + 10-question battery, Streamlit chat with
live thinking.

## What is deleted

The five-stage pipeline (Planner/DataScout/Analyst/Narrator as separate calls)
and every inter-stage schema, the toolkit proposal layer, the standalone
codegen prompt. Their proven CONTENT (prompt method, sandbox, helpers, gates)
is redistributed into Designer / Executor / Writer + knowledge files.

## Open items

- First draft of `2_mrx/menu.md` (distilled from the multirow manual + eval
  learnings) and `3_gold_standard.md` (the PRINCIPLES, distilled from the
  user's gold-example note — the example shows the principles in action once,
  it is not a template) — then red-penned by the user: both are desk judgment.
- Document the explain-type risk types (e.g. Risk Explain — a multirow RISK
  TYPE, not a separate view) in the multirow manual + a capability-menu line;
  needs the user's example of its parameters/output.
- Optional: smolagents' standalone `LocalPythonExecutor` as sandbox hardening;
  self-hosted Phoenix for trace browsing.
- Dynamic skill/knowledge router (the file format is ready; build it only when
  knowledge domains multiply beyond one system prompt's comfort).
