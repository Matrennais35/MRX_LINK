# How MRX Analyst works — behind the scenes

*The companion to `VISION.md` (which says WHY it's built this way). This
document says WHAT actually happens, file by file, when a question is asked.*

---

## The 30-second version

```
User question (Streamlit chat)
   │
   ▼
1. DESIGN     mrx_analyst/design/       one LLM call → the BLUEPRINT
   │                                    (what the answer will look like +
   │                                     which data fills it — or a question
   │                                     back to the user if too ambiguous)
   ▼
2. EXECUTE    mrx_analyst/execute/      an adaptive tool loop (like Claude
   │                                    Code): the model interleaves
   │                                    fetch_mrx / run_python / read_knowledge
   │                                    until it can write the note
   ▼
3. WRITE      mrx_analyst/write/        the note is assembled (sections +
   │                                    charts/tables), then ONE Critic check;
   │                                    findings re-enter the loop once
   ▼
The desk note (+ full audit trail, all persisted)
```

The composition lives in **`mrx_analyst/run.py :: run_question()`** — read it
top to bottom and you've read the system.

---

## The life of a question, in detail

### 0. Context loading (`run.py :: _load_history`)

Before anything else, the conversation's past is loaded from the catalog:
- **prior turns** (question + answer text) for conversational context;
- **previously fetched datasets** of this conversation — each is profiled and
  seeded into the run as zero-cost evidence AND into the python namespace, so
  a follow-up like "now split that by desk" needs no new MRX call.
- Conversations longer than 12 turns are **summarized** (older turns condensed
  to bullets by a low-effort LLM call, last 6 kept verbatim).

### 1. DESIGN — the pivotal step (`design/designer.py`)

One structured-output LLM call (effort=high). Its system prompt is assembled
**from knowledge files, not code** (`common/knowledge.py`):

| knowledge file | role in the Designer |
|---|---|
| `knowledge/1_intent.md` | how to read the question, defaults, when to ask back |
| `knowledge/3_answer_standard.md` | response MODES + the principles to derive this question's bar |
| `knowledge/2_mrx/menu.md` | the capability menu — what MRX can serve (incl. Risk Explain) |
| `knowledge/desk.md` | your limits/conventions (empty template until filled) |

The output is the **Blueprint** (`design/blueprint.py`) — the per-question
contract:
- `target` — the question behind the words;
- `sections[]` — each with `must_establish` (the quality contract),
  `data_needed`, and `artifact` (line chart / table / waterfall / none);
- `fetches[]` — natural-language data requests, each `now` or
  `after: <section>` (adaptive drills whose parameters depend on earlier
  results);
- `clarification` — if set, the run STOPS and the question is asked back to
  the user (their reply re-enters the Designer with the conversation history,
  per the round-trip rule in `1_intent.md`).

The Blueprint is a **contract of qualities, not a straitjacket**: the Executor
may amend it in-flight (retitle/merge/split sections) with stated reasons.

### 2. EXECUTE — the tool loop (`execute/loop.py`)

The Claude-Code pattern: `llm.bind_tools([...])` and iterate — the model
thinks (visible text), calls tools, reads results, decides again. Hard caps
are plain code: `MAX_STEPS = 10` iterations; if hit, the model is forced to
write the note from what exists (never lose the work).

The loop's client is the **"tools" tier** — built WITHOUT `reasoning_effort`
(Azure rejects function tools + reasoning_effort on chat/completions; learned
live).

**The three tools:**

**`fetch_mrx(request)`** — `execute/tools/fetch_mrx.py`. Takes natural
language ("daily total FX Vega on GFXOPEMK, history dates, COB 2026-06-08 to
2026-07-06"). Inside, in order:
1. a **nested URL-builder LLM call** (`mrx/generate_link.py`) holding the full
   multirow manual + reference tables (`knowledge/2_mrx/manuals/`) — this
   50KB of MRX knowledge never enters the main loop's context;
2. the **validation gate** (`mrx/validation.py`) — deterministic checks of
   every parameter against the reference tables; a rejection retries the
   URL-builder with the error (up to 3 attempts);
3. the **reuse check** (`mrx/reuse.py`) — if a cataloged dataset covers the
   same parameters, it's returned at ZERO budget cost;
4. the **hard fetch budget** (`execute/session.py :: FetchBudget`, default 6
   per question, thread-locked) — exhaustion returns a refusal message;
5. the download (`mrx/data_fetch.py` via pymrx), with an **'Invalid
   Parameters' frame detected as a failure** (not silently analyzed) and a
   **180s wall timeout** (a hung MRX call once froze a run for 5+ minutes);
6. **profiling** (`mrx/profiler.py`) — a deterministic summary (value columns,
   sign mix, concentration, top movers; Depth-hierarchy and wide-date aware)
   plus VERBATIM sample rows (head 12, wide frames elided) returned to the
   model — it sees real columns and values, not only a summary;
7. catalog persistence, so future questions can reuse the frame.

Several `fetch_mrx` calls in one model response run **in parallel** (the
budget's lock keeps the cap exact). All failures return as TEXT so the model
self-corrects in its next iteration — there is no separate retry subsystem.

**`run_python(code)`** — `execute/tools/run_python.py`. Free pandas/matplotlib
in a **persistent namespace** (a Jupyter-kernel feel): every fetched frame is
there under its label, plus `pd`, `np`, `plt`, `helpers`, and `section()`.
- `helpers/` (`ops.py`, `charts.py`) is the OPTIONAL tested library — leaf-
  aware attribution/variance/concentration, `trend` (dated jumps),
  `position_change` (new/expired/unwound/existing), chart builders. The model
  may use them or write raw pandas; nothing is mandated.
- `section(title, table=, chart=, full=)` attaches a computed artifact to a
  blueprint section (`full=True` = extraction mode: the UI renders every row)
  AND echoes the table back into the tool result — the model holds the
  values verbatim when it writes the note.
- Errors return as the tool result → the model fixes its code next iteration.
- What the model should know about MRX frames (Depth double-counting, wide
  date columns, Total rows...) is in its prompt from `knowledge/2_mrx/reading.md`.

**`read_knowledge(document)`** — serves the manuals/reference tables on
demand, for questions ABOUT MRX itself ("what feeds FX Gamma?"). Progressive
disclosure: index in the prompt, content pulled as a visible tool call.

**The final message with no tool calls IS the note**: markdown, executive
summary first (no heading), then `## <section>` headings.

### 3. WRITE + CRITIC (`write/`)

- `writer.py :: assemble()` splits the note on its `##` headings, attaches
  each section's artifacts by title, and builds the `Answer`
  (`common/answer.py`: narrative + ordered `Section`s). A blueprint section
  that was neither written nor filled becomes a **visible unfilled section
  with its contract as the reason** — silent drops are structurally impossible.
- `critic.py :: check()` — ONE anchored LLM call (effort=low): (1) every
  figure in the note must appear in/derive from the artifacts; (2) every
  section contract delivered or honestly flagged. On "revise", the critique
  **re-enters the same loop with tools live** (`loop.refine()`, max 4 extra
  steps) — so "you never computed X" is fixed by computing X. One refine,
  cap in code, then the note ships regardless. A critic crash never loses
  the note.

### Persistence (`run.py :: _persist` → `storage/catalog.py`)

Everything survives a refresh: the turn (question, note text, the python code
that ran), the full **Step trace** (every model iteration, tool call, gate
event — the audit trail), every chart as PNG (`{turn_id}_{n}.png`), and each
fetched dataset (SQLite metadata + parquet payload) for cross-question reuse.
User feedback (`storage/feedback.py`) appends to `feedback.txt`/`.jsonl`
pairing each verdict with the blueprint.

### The UI (`ui/`)

`analyst_app.py` → `ui/app.py`. One **emit(kind, payload)** event channel
(`common/events.py`) feeds the live thinking box: the Designer's blueprint
summary, the executor's narrated steps, fetch progress, the Critic's verdict.
(Events from parallel fetch threads are buffered and flushed on the main
thread — Streamlit APIs are script-thread-only.) `ui/render.py` renders the
note (sections in order, charts at controlled size, analysis tables capped at
a preview / extraction tables complete), the blueprint expander, the trace,
and the feedback form. Conversation identity lives in the URL (`?c=conv_...`);
past turns replay from the catalog with their persisted charts and traces.

---

## The knowledge layer — how behavior is changed WITHOUT code

`common/knowledge.py` loads `knowledge/*.md` **fresh on every question** — an
edit applies to the next question, no restart. Each file has frontmatter
(`name`, `when_to_use`, `examples`) acting as index lines. A test enforces
the assembled prompt stays under a size budget.

The **diagnosis rule** (from VISION.md): every failure maps to exactly one
file —

| symptom | edit |
|---|---|
| misread the target / wrong response mode | `1_intent.md` or `3_answer_standard.md` |
| wrong view, bad URL, wrong window | `2_mrx/manuals/` (and its tables) |
| designed data MRX can't serve / missed a capability (e.g. Risk Explain) | `2_mrx/menu.md` |
| mangled frame handling, double counts | `2_mrx/reading.md` (+ `helpers/` if deterministic) |
| right facts, unsatisfying note | `3_answer_standard.md` |
| wrong units/limits/conventions | `desk.md` |

`knowledge/BACKLOG.md` collects observed gaps; every edit is proven by
re-running the battery.

---

## The safety gates (all plain code — no model ever holds one)

| gate | where | value |
|---|---|---|
| fetch budget | `execute/session.py :: FetchBudget.acquire()` | 6/question, thread-locked |
| URL validation | `mrx/validation.py` (tables-driven) | every fetch, never bypassed |
| loop step cap | `execute/loop.py :: MAX_STEPS` | 10 (+4 for the one refine) |
| fetch wall timeout | `execute/loop.py :: FETCH_TIMEOUT_S` | 180s |
| URL-builder retries | `execute/tools/fetch_mrx.py :: MAX_URL_ATTEMPTS` | 3 |
| refine cap | `run.py` (one critic round) | 1 |
| audit trail | `common/trace.py` Steps → catalog | every step persisted |

---

## The harnesses

- **`slice_run.py`** — one question, live, printing blueprint + trace + note
  + per-phase timings. The daily debug tool.
- **`blueprint_run.py`** — the Designer ALONE over the review battery (with
  threaded conversations) → one markdown of blueprints. Judges the pivotal
  step cheaply, before any fetch.
- **`eval_run.py`** — the full battery (14 questions, 9 conversations)
  through the whole engine → one self-contained report: metrics table
  (timings, budget/reuse, python failures, timeouts, refined/clarified
  flags), then per question the blueprint, trace, note, embedded charts, and
  the exact code that ran.

## Testing (`tests/mrx_analyst/`, 112 tests)

Fakes stand in for the LLM (scripted tool calls) and pymrx (stubbed module),
so the invariants are provable offline: budget exactness under parallelism,
zero-cost reuse, namespace persistence, in-loop self-correction, step-cap
forcing, timeout behavior, visible gaps, clarification short-circuit, critic
refine actually computing, knowledge prompt budget, plus golden tests for
every `helpers` op on real MRX frame shapes and the validation gate against
the real manual.

## Extending the system

- **New MRX capability** (a view, a risk type like Risk Explain): document it
  in `2_mrx/manuals/` + one line in `menu.md`. No code.
- **New analytical move**: first ask if MRX serves it natively (menu). Only
  generic math goes into `helpers/` — with golden tests.
- **Desk specifics** (limits, conventions, nicknames): `desk.md`.
- **LLM tiers**: `run.py :: ROLE_EFFORT` (designer=high, url=medium,
  critic=low, loop="tools" — the no-reasoning_effort client).

## The simulator — the whole framework without MRX (`MRX_SIM=1`)

`mrx/sim.py`: set `MRX_SIM=1` and the default view becomes a SIMULATOR —
same real validation gate, same URL parameters, same frame shapes (wide
history, compare, Risk Explain New/Passive/Expired, Depth hierarchies, deal
labels), but synthetic data from a deterministic world (stable across
restarts) with a PLANTED STORY: a dated jump, a known driver/offset, a known
explain split — exposed via `SimMRXView.truth()`.

```
MRX_SIM=1 streamlit run analyst_app.py     # macOS/linux
set MRX_SIM=1 && streamlit run analyst_app.py   # Windows cmd
$env:MRX_SIM=1; streamlit run analyst_app.py    # PowerShell
```

Uses: demo mode (no production MRX touched); offline development; and
GROUND-TRUTH EVALS — a live eval can only judge plausibility, but against
the sim you can assert the note found the planted jump date, the planted
driver, and the planted explain split. Still requires the LLM (only the
data is fake).

## Recovering the past

Full history is in git; the last commit of the previous (5-agent pipeline)
engine is tagged **`pipeline-final`** (`git show pipeline-final:app.py`, or
check out the tag entirely).
