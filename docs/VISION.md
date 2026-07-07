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
frontmatter with `name`, `when_to_use`, `examples` + the markdown content.
The frontmatter's job is to be INDEX LINES (one line per knowledge unit),
not router food. Today ALL files are assembled into the prompts by
`prompts.py` — one deep domain, and the Designer must ALWAYS see the full
capability menu (menu-blindness was the eval's biggest quality failure; no
routing mechanism may ever hide a capability from the design step).
Capability-menu entries carry `when_to_use` + example questions the same way.

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
  3_answer_standard.md ★ ONE file: what a complete answer IS and how it
                       reads — RESPONSE MODES first (analysis note /
                       extraction / plot / fact lookup / MRX-meta: the size
                       and shape of the answer), then the analysis
                       principles (quantify+reconcile, date the moves,
                       decompose the why via Risk Explain, concentration
                       with both denominators, one-line context, claim
                       nothing unsupported / everything derivable, brevity
                       is quality) and the writing mechanics. Never a
                       template — the Designer instantiates it into each
                       question's Blueprint. (Merged from the former
                       gold_standard + note files: the substance/form split
                       failed the diagnosis rule — 'unsatisfying answer'
                       mapped to two files.) Owned and red-penned by the
                       user.                    [Designer + Writer + Critic + eval]
  desk.md              The user's desk context: limits, conventions,
                       nicknames (empty template until filled).           [Designer + Writer]
  BACKLOG.md           Harvested knowledge gaps (see the learning loop).
```

## The repository is the vision (the approved tree)

The folder architecture teaches the split: three phase folders, knowledge as
the product, MRX machinery and the optional library each in their own home.

```
MRX_LINK/
├── knowledge/                    ★ THE PRODUCT (edited, not coded)
│   ├── 1_intent.md               what does the user want to achieve
│   ├── 2_mrx/
│   │   ├── menu.md               capability menu (designer-facing index)
│   │   ├── manuals/              URL manuals + tables (fetcher-facing)
│   │   └── reading.md            how to read returned frames
│   ├── 3_answer_standard.md      response modes + principles + writing method
│   ├── desk.md                   limits/conventions
│   └── BACKLOG.md                harvested knowledge gaps
├── mrx_analyst/
│   ├── run.py                    run_question(): design → execute → write
│   ├── design/                   ── PHASE 1: the pivotal step ──
│   │   ├── designer.py           the one LLM call
│   │   └── blueprint.py          the Blueprint contract
│   ├── execute/                  ── PHASE 2: fill the blueprint ──
│   │   ├── loop.py               tool loop (step cap, one-redesign cap)
│   │   ├── session.py            namespace · artifacts · evidence · budget
│   │   └── tools/
│   │       ├── fetch_mrx.py      the gated fetch (uses mrx/)
│   │       └── run_python.py     sandbox + section()
│   ├── write/                    ── PHASE 3: the note ──
│   │   ├── writer.py             report assembly from blueprint + artifacts
│   │   └── critic.py             the anchored check (one refine)
│   ├── mrx/                      MRX interface machinery: generate_link,
│   │   │                         validation, data_fetch, reuse, models
│   │   └── profiler.py           (MRX-frame-aware: Depth/Totals/wide dates)
│   ├── helpers/                  the OPTIONAL tested analysis library
│   │   └── ops.py charts.py      (available in run_python, never mandated)
│   ├── common/                   answer, trace, events, errors, llm,
│   │                             knowledge.py (loads/indexes knowledge/)
│   ├── storage/                  catalog.py feedback.py
│   └── ui/                       app.py render.py sidebar.py format.py
├── analyst_app.py · analyst_debug.py · blueprint_run.py · eval_run.py
└── tests/mrx_analyst/            mirrored: test_design_* test_execute_* test_write_*
```

Tools vs helpers, structurally: `execute/tools/` are the TWO things the loop
can call; `helpers/` is the optional library inside the code it writes.
`tests/` mirror the split so a failing test names its phase — the diagnosis
rule extended to code.

## The diagnosis rule (the falsifiable maintenance contract)

Every failure — a 👎, an eval miss, a Critic finding — must map to **exactly
one** home:

- misread the target / bad output design → `1_intent.md` or `2_mrx/menu.md`
  (was it intent, or menu-blindness? the blueprint makes this visible)
- wrong view / bad URL / wrong window → `2_mrx/manuals/`
- mangled frame handling, double counts → `2_mrx/reading.md` (+ helpers if deterministic)
- unfulfilled blueprint (missing computation) → execution problem (harness/
  helpers); fulfilled-but-unsatisfying blueprint (bar set wrong or note reads
  badly) → `3_answer_standard.md` or `2_mrx/menu.md`
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
(`when_to_use`/`examples` as index metadata), the IDEA of scaling knowledge
beyond one prompt (but via progressive disclosure, not their middleware — see
open items), their knowledge-document writing style (vocabulary,
interpretation rules, worked workflows — the template for
`menu.md`/`reading.md`), and long-thread summarization.

## What exists and is kept (the assets)

Views layer (multirow manual/tables → `2_mrx/manuals/`), gated fetch with
reuse + budget (`tools/mrx_fetch.py`), deterministic profiler (wide-date +
Depth-aware; profiles summarize BULK data — but SMALL computed tables and
sample rows enter the model's context VERBATIM: the LLM_CCR comparison
proved the writer must hold what it describes, or the prose reads thin),
sandbox executor, tested helpers (`ops.py`, `charts.py`),
catalog (datasets/turns/steps/charts), Answer/Section shapes + renderer,
feedback capture, eval harness + 10-question battery, Streamlit chat with
live thinking.

## What is deleted

The five-stage pipeline (Planner/DataScout/Analyst/Narrator as separate calls)
and every inter-stage schema, the toolkit proposal layer, the standalone
codegen prompt. Their proven CONTENT (prompt method, sandbox, helpers, gates)
is redistributed into Designer / Executor / Writer + knowledge files.

## Open items

- Dense rewrite of `2_mrx/menu.md` + `2_mrx/reading.md` (LLM_CCR style, now
  with live evidence: Risk Explain = CritPrdRiskExpain/RowGrpRiskCmpnt with
  New/Passive/Expired components) — then red-penned by the user with
  `3_answer_standard.md`: desk judgment.
- Document the explain-type risk types (e.g. Risk Explain — a multirow RISK
  TYPE, not a separate view) in the multirow manual + a capability-menu line;
  needs the user's example of its parameters/output.
- Optional: smolagents' standalone `LocalPythonExecutor` as sandbox hardening;
  self-hosted Phoenix for trace browsing.
- Scaling knowledge beyond one prompt, WHEN domains multiply: PROGRESSIVE
  DISCLOSURE, agent-pulled (the Claude Code pattern) — the frontmatter index
  lines stay always-visible in the prompt; full content is pulled on demand
  via a trivial `read_knowledge("<name>")` tool (or packaged inside the
  domain tool that needs it, like the manuals inside `fetch_mrx` today).
  Chosen over LLM_CCR's middleware activation (hidden state, activation
  churn, a router to be wrong): every pull is a visible, traced tool call,
  and nothing is ever invisible to the model. ~30 lines when needed.
