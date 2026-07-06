"""The bounded controller loop — the pipeline's orchestration core.

"Decide one step at a time, look at the result, decide again" — capped at a
hard fetch limit, every fetch through the shared validation gate, every
decision recorded for audit. See docs/agent_loop_design.md.

Deliberately thin: it reuses `fetch.get_view` for every fetch (plan ->
validate_plan -> deterministic reuse-check -> fetch -> catalog save), so
there is exactly one validation-gated fetch path, never a second one that
could drift. The loop's only responsibilities are (1) the hard fetch cap,
enforced in this file's own code, and (2) accumulating the step trace.
"""

from dataclasses import dataclass
from typing import Optional

from . import catalog, fetch, smart_pandas
from .fetch import ViewResult
from .pipeline_errors import AnswerError
from .smart_pandas import AnswerResult
from .step import StepDecision, decide_next_step, plan_analysis
from ..views import DEFAULT_VIEW
from ..views.base import View

# Default hard cap on MRX fetches per question. A plain count (not a cost
# budget): per-fetch cost isn't predictable (a deal/row-level "fetch all
# deals" is far heavier than a node-level fetch), so this bounds the NUMBER
# of MRX round-trips, accepting that N heavy fetches is the worst case.
# Guarding the specifically-expensive deal-level fetch is a known follow-up,
# deliberately not built yet (see the design doc). Checked in this file's own
# loop code — never handed to the model, never a framework setting — so it
# can't drift the way LangGraph's super-step-counting recursion_limit does.
DEFAULT_MAX_FETCHES = 4

# Backstop on total loop iterations, independent of the fetch cap: an "answer"
# step does no fetch, so in principle a model could emit "answer" then somehow
# never terminate. max_steps guarantees the loop always ends. Set a little
# above max_fetches so a full run (max_fetches fetches, then one answer
# decision) still fits.
DEFAULT_MAX_STEPS = DEFAULT_MAX_FETCHES + 2


@dataclass
class StepRecord:
    """One iteration's audit record: the decision the model made, and (for a
    fetch) how that fetch resolved. Persisted per turn as the "why each fetch
    happened" chain, and its `reasoning` is threaded into the answer prompt as
    per-frame provenance (same data, used twice — see the design doc).
    """
    step_num: int
    action: str
    reasoning: str
    fetch_query: str = ""
    # Set only for a fetch step that actually ran: how that view resolved,
    # so the trace records not just "we fetched by-desk" but whether it hit
    # MRX fresh or reused already-cataloged data.
    fetched_label: Optional[str] = None
    reused_dataset_id: Optional[str] = None
    # Set when the model wanted to fetch but the hard cap refused it — the
    # trace must show the cap fired, not silently look like the model chose
    # to stop on its own.
    capped: bool = False


@dataclass
class LoopResult:
    """The result of one controller-loop run: the final answer, the views
    gathered to produce it, and the step trace (the audit chain persisted per
    turn). `views` and `answer` are what the UI renders; `steps` is the
    "how was this computed" investigation trace.
    """
    answer: AnswerResult
    views: list  # list[ViewResult], in fetch order
    steps: list  # list[StepRecord], in decision order
    plan: Optional[object] = None  # the AnalysisPlan (step.AnalysisPlan) reasoned up front, if any


def _provenance_label(view: ViewResult, record: StepRecord) -> str:
    """The label a gathered frame is presented under — its description plus
    WHY it was fetched (the step's reasoning). Threading the reasoning here
    is the fix for the drill-down-relationship gap (design doc open-question
    #4): without it, the answer stage sees sibling frames with no signal that
    one was drilled from another.
    """
    base = view.plan.intent or view.query
    why = record.reasoning.strip()
    return f"{base} (fetched because: {why})" if why else base


def run_agent_loop(
    llm,
    query: str,
    *,
    view: View = DEFAULT_VIEW,
    min_confidence: float = 0.7,
    max_attempts: int = 3,
    max_fetches: int = DEFAULT_MAX_FETCHES,
    max_steps: int = DEFAULT_MAX_STEPS,
    on_stage=None,
    on_step=None,
    on_token=None,
    session_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> LoopResult:
    """Run the bounded controller loop for one question.

    Read top-to-bottom, this IS the pipeline — three named stages in order:

      1. `_load_context`   — seed this conversation's prior data + history
                             (STAGE 0: understand what we already have).
      2. `_investigate`    — the decide -> fetch -> deep-dive loop
                             (STAGES 1-4: understand the question, plan, fetch,
                             drill in), bounded by the hard `max_fetches` cap.
      3. `_answer`         — analyze the gathered data or respond in prose
                             (STAGES 5-6: analyze, summarize).

    The stages are only re-seamed for legibility: each delegates to the exact
    same per-stage primitives as before (`decide_next_step`, `fetch.get_view`,
    `smart_pandas.ask`/`respond`), in the same order, with no behavior change.

    `view` selects which MRX view every fetch this run plans/validates/executes
    against (defaults to the registered default view; per-question view
    selection is a later concern once a second view exists).

    Returns a LoopResult carrying the final answer, the gathered views, and
    the full step trace (the audit chain persisted per turn).

    `on_stage`/`on_token`/`session_id`/`conversation_id`/`min_confidence`/
    `max_attempts` mean the same for the fetch primitives — they're passed
    straight through to the reused `fetch.get_view`/`smart_pandas.ask`.
    """
    session_id = session_id or fetch.DEFAULT_SESSION_ID

    # STAGE 0 — context: what this conversation already knows.
    views, gathered, history = _load_context(conversation_id)

    # STAGE 0.5 — PLAN: reason about the target, the breakdown that reveals it,
    # the representation, and what a good answer must contain — BEFORE fetching.
    # Sets direction + the quality bar for every stage below. Never raises: a
    # planning hiccup degrades to no plan (the loop then behaves as it did
    # before this stage), it doesn't fail the question.
    if on_stage:
        on_stage("plan:analysis")
    try:
        plan = plan_analysis(llm, query, gathered=gathered, history=history)
    except Exception:
        plan = None

    # STAGES 1-4 — investigate: decide, fetch, drill in (bounded), guided by the
    # plan's target so each step is purposeful rather than reactive.
    steps: list = []
    answer_mode = _investigate(
        llm, query, views, gathered, history, plan=plan,
        view=view, min_confidence=min_confidence, max_attempts=max_attempts,
        max_fetches=max_fetches, max_steps=max_steps,
        session_id=session_id, conversation_id=conversation_id,
        steps=steps, on_stage=on_stage, on_step=on_step,
    )

    # STAGES 5-6 — answer: analyze the gathered data, or respond in prose, using
    # the representation the plan called for.
    if on_stage:
        on_stage("answer")
    answer = _answer(
        llm, query, answer_mode, views, gathered, history, plan=plan, on_token=on_token
    )
    return LoopResult(answer=answer, views=views, steps=steps, plan=plan)


def _load_context(conversation_id: Optional[str]) -> tuple[list, list, list]:
    """STAGE 0 — seed this conversation's already-known context, so the very
    first decision can answer from prior data instead of being forced to fetch.

    Returns `(views, gathered, history)`:
    - `views`: prior ViewResults reconstructed from the catalog.
    - `gathered`: (label, df) pairs handed to `decide_next_step` and, at the
      end, to the answer stage — seeded with THIS conversation's already-
      fetched data so a follow-up ("plot the variation") can be answered
      directly from what a prior turn fetched, with no new MRX call. Each turn
      is a fresh `run_agent_loop` call that would otherwise start blind.
    - `history`: prior (question, narrated-answer) turns, so the orchestrator
      can answer conversation-level questions (summaries, follow-ups).

    Everything degrades to empty on any catalog error — same "reuse is an
    optimization, its failure just means a fetch happens" stance as
    `fetch.find_reusable_dataset`.
    """
    views: list = []
    gathered: list = []
    history: list = []
    if not conversation_id:
        return views, gathered, history

    # Prior datasets as available context BEFORE step 1.
    try:
        for dataset in catalog.list_for_conversation(conversation_id=conversation_id):
            df = fetch.load_reused_df(dataset.id)
            if df is None:
                continue
            context_view = ViewResult(
                query=dataset.query, plan=dataset.plan, df=df, attempts=0,
                reused_dataset_id=dataset.id,
            )
            views.append(context_view)
            label = f"{dataset.description} (from an earlier question: {dataset.query!r})"
            gathered.append((label, df))
    except Exception:
        views, gathered = [], []

    # The recent conversation (prior questions + narrated answers).
    try:
        history = catalog.list_turns(conversation_id=conversation_id)
    except Exception:
        history = []

    return views, gathered, history


def _investigate(
    llm, query: str, views: list, gathered: list, history: list, *,
    plan=None, view: View, min_confidence: float, max_attempts: int,
    max_fetches: int, max_steps: int,
    session_id: str, conversation_id: Optional[str],
    steps: list, on_stage=None, on_step=None,
) -> str:
    """STAGES 1-4 — the decide -> fetch -> deep-dive loop.

    Each iteration asks `decide_next_step` whether to fetch once more or answer
    now, given everything gathered so far. A "fetch" runs the EXISTING
    `fetch.get_view` (planned, validated, reuse-checked and catalog-saved
    through the shared validation gate); "analyze"/"respond" ends the loop. The
    hard `max_fetches` cap is enforced HERE — the model can *want* more data,
    but the loop simply stops calling `fetch.get_view`.

    Mutates `views`, `gathered` and `steps` in place (they're the run's
    accumulators, also seeded by `_load_context`). Returns the chosen
    `answer_mode` — "analyze" (compute over data) or "respond" (direct prose) —
    which the answer stage dispatches on.
    """
    conv_for_view = conversation_id or fetch.DEFAULT_SESSION_ID

    # `views` may already hold seeded context, so it's NOT a reliable "did we
    # fetch anything" signal for the cap or the empty-answer guard. Track
    # THIS run's fresh fetches separately.
    fresh_fetch_count = 0
    # Set when the loop decides to answer: "analyze" (compute over data) or
    # "respond" (direct prose, no data needed). None until decided.
    answer_mode: Optional[str] = None

    for step_num in range(1, max_steps + 1):
        if on_stage:
            on_stage(f"decide:{step_num}")
        decision = decide_next_step(llm, query, gathered, history=history, plan=plan)

        # Surface the decision's actual CONTENT live (its action + reasoning +
        # what it's about to fetch), so the UI can show the loop's real
        # thinking step by step rather than an opaque "Building the MRX
        # plan...". Additive: no-op if no on_step callback is given.
        if on_step:
            on_step(step_num, decision)

        if decision.action in ("analyze", "respond"):
            steps.append(StepRecord(
                step_num=step_num, action=decision.action, reasoning=decision.reasoning,
            ))
            answer_mode = decision.action
            break

        # action == "fetch"
        if fresh_fetch_count >= max_fetches:
            # The model wanted more data but the hard cap refuses it. The cap
            # counts THIS run's fresh MRX fetches only — seeded conversation
            # context doesn't consume the budget. Record that the cap fired
            # (not a model-chosen stop) and analyze what we have.
            steps.append(StepRecord(
                step_num=step_num, action="fetch", reasoning=decision.reasoning,
                fetch_query=decision.fetch_query, capped=True,
            ))
            answer_mode = "analyze"
            break

        result = fetch.get_view(
            llm, decision.fetch_query or query,
            view=view,
            session_id=session_id, conversation_id=conv_for_view,
            min_confidence=min_confidence, max_attempts=max_attempts,
            on_stage=on_stage, stage_suffix=f":{step_num}",
        )
        record = StepRecord(
            step_num=step_num, action="fetch", reasoning=decision.reasoning,
            fetch_query=decision.fetch_query,
            fetched_label=result.plan.intent or result.query,
            reused_dataset_id=result.reused_dataset_id,
        )
        steps.append(record)
        views.append(result)
        gathered.append((_provenance_label(result, record), result.df))
        fresh_fetch_count += 1

    # If the loop exhausted max_steps without choosing to answer, fall back to
    # analyzing whatever was gathered (or responding if nothing was).
    if answer_mode is None:
        answer_mode = "analyze" if gathered else "respond"
    return answer_mode


def _answer(
    llm, query: str, answer_mode: str, views: list, gathered: list, history: list,
    *, plan=None, on_token=None,
) -> AnswerResult:
    """STAGES 5-6 — turn the investigation into an answer.

    `answer_mode == "respond"`: a direct prose answer, no data computation —
    valid even with no data (e.g. "summarise the conversation", a concept
    question). This is why the old "nothing gathered => error" guard no longer
    applies blanket: a respond answer legitimately needs no data.

    `answer_mode == "analyze"`: compute over the gathered data (generate + run
    pandas, then narrate/synthesize). Requires data — with nothing gathered it
    raises a clean AnswerError rather than calling the answer stage with
    nothing, the same "degrade to a caught error" stance the fetch primitives
    take elsewhere.
    """
    if answer_mode == "respond":
        data_descriptions = [label for label, _ in gathered]
        return smart_pandas.respond(
            llm, query, history=history, data_descriptions=data_descriptions, on_token=on_token
        )

    # answer_mode == "analyze": compute over the data.
    if not gathered:
        raise AnswerError(
            "The question needs data analysis but no data was available to "
            "compute over. Try rephrasing the question."
        )
    representation = plan.representation if plan is not None else None
    return _answer_over_gathered(
        llm, query, views, gathered, representation=representation, on_token=on_token
    )


def steps_to_traces(steps: list, *, turn_id: str, conversation_id: str) -> list:
    """Convert a LoopResult's in-memory StepRecords into persistable
    catalog.StepTrace rows for one turn. Kept here (not in app.py) so the
    mapping between the loop's record shape and the stored shape lives next
    to the loop that produces it. `None` fields (a fetch that didn't reuse,
    an answer step with no fetch label) become "" so the NOT NULL columns are
    satisfied without the caller special-casing them.
    """
    return [
        catalog.StepTrace(
            id=catalog.new_step_id(),
            turn_id=turn_id,
            conversation_id=conversation_id,
            step_num=s.step_num,
            action=s.action,
            reasoning=s.reasoning,
            fetch_query=s.fetch_query or "",
            fetched_label=s.fetched_label or "",
            reused_dataset_id=s.reused_dataset_id or "",
            capped=s.capped,
        )
        for s in steps
    ]


def _answer_over_gathered(llm, query: str, views: list, gathered: list, *, representation=None, on_token=None) -> AnswerResult:
    """Hand the accumulated frames to the existing answer stage.

    One gathered frame => the single-dataframe path. Several => the existing multi-frame path, with each
    frame carrying its provenance label (see `_provenance_label`) so the
    model knows how a drilled-down child relates to its parent.

    `representation` (from the analysis plan, if any) tells the code-gen what
    form the answer should take — a waterfall for attribution, a line for a
    trend, etc. — so the view is chosen by the plan's reasoning, not defaulted.
    """
    if len(gathered) == 1:
        _, df = gathered[0]
        return smart_pandas.ask(df, query, llm, original_query=query, representation=representation, on_token=on_token)

    # sanitize_names takes (label, df) pairs and turns the provenance labels
    # into valid, collision-free exec() variable names.
    named = smart_pandas.sanitize_names(gathered)
    return smart_pandas.ask(named, query, llm, representation=representation, on_token=on_token)
