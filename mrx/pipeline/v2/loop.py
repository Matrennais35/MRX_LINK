"""The bounded controller loop — V2's core.

Replaces V1's "classify the whole question once, then execute a fixed plan"
with "decide one step at a time, look at the result, decide again" — capped
at a hard fetch limit, every fetch still through V1's validation gate, every
decision recorded for audit. See docs/agent_loop_design.md.

Deliberately thin: it reuses V1's `orchestrator._get_view` for every fetch
(plan -> validate_plan -> deterministic reuse-check -> fetch -> catalog save),
so there is exactly one validation-gated fetch path, never a second one that
could drift. The loop's only new responsibilities are (1) the hard fetch cap,
enforced in this file's own code, and (2) accumulating the step trace.
"""

from dataclasses import dataclass, field
from typing import Optional

from .. import catalog, orchestrator, smart_pandas
from ..orchestrator import ViewResult
from ..pipeline_errors import AnswerError
from ..smart_pandas import AnswerResult
from .step import StepDecision, decide_next_step

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
    """V2's equivalent of V1's PipelineResult, plus the step trace.

    Shaped so app.py can render it much like a PipelineResult (it has an
    `answer` and the gathered `views`), with `steps` as the new audit chain.
    """
    answer: AnswerResult
    views: list  # list[ViewResult], in fetch order
    steps: list  # list[StepRecord], in decision order


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
    min_confidence: float = 0.7,
    max_attempts: int = 3,
    max_fetches: int = DEFAULT_MAX_FETCHES,
    max_steps: int = DEFAULT_MAX_STEPS,
    on_stage=None,
    on_token=None,
    session_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> LoopResult:
    """Run the bounded controller loop for one question.

    Each iteration asks `decide_next_step` whether to fetch once more or
    answer now, given everything gathered so far. A "fetch" runs the EXISTING
    `orchestrator._get_view` (so it's planned, validated, reuse-checked and
    catalog-saved exactly like a V1 fetch); an "answer" ends the loop. The
    hard `max_fetches` cap is enforced here, in this function — the model can
    *want* more data, but the loop simply stops calling `_get_view`.

    Returns a LoopResult carrying the final answer, the gathered views, and
    the full step trace (the audit chain persisted per turn).

    `on_stage`/`on_token`/`session_id`/`conversation_id`/`min_confidence`/
    `max_attempts` mean the same as in `orchestrator.run` — they're passed
    straight through to the reused `_get_view`/`smart_pandas.ask`.
    """
    session_id = session_id or orchestrator.DEFAULT_SESSION_ID
    conv_for_view = conversation_id or orchestrator.DEFAULT_SESSION_ID

    views: list = []
    steps: list = []
    # (label, df) pairs handed to decide_next_step and, at the end, to the
    # answer stage — kept in sync with `views` but reduced to what those two
    # consumers need.
    gathered: list = []

    for step_num in range(1, max_steps + 1):
        if on_stage:
            on_stage(f"decide:{step_num}")
        decision = decide_next_step(llm, query, gathered)

        if decision.action == "answer":
            steps.append(StepRecord(
                step_num=step_num, action="answer", reasoning=decision.reasoning,
            ))
            break

        # action == "fetch"
        if len(views) >= max_fetches:
            # The model wanted more data but the hard cap refuses it. Record
            # that the cap fired (not a model-chosen stop) and answer with
            # what we have — never silently exceed the bound.
            steps.append(StepRecord(
                step_num=step_num, action="fetch", reasoning=decision.reasoning,
                fetch_query=decision.fetch_query, capped=True,
            ))
            break

        view = orchestrator._get_view(
            llm, decision.fetch_query or query,
            session_id=session_id, conversation_id=conv_for_view,
            min_confidence=min_confidence, max_attempts=max_attempts,
            on_stage=on_stage, stage_suffix=f":{step_num}",
        )
        record = StepRecord(
            step_num=step_num, action="fetch", reasoning=decision.reasoning,
            fetch_query=decision.fetch_query,
            fetched_label=view.plan.intent or view.query,
            reused_dataset_id=view.reused_dataset_id,
        )
        steps.append(record)
        views.append(view)
        gathered.append((_provenance_label(view, record), view.df))

    if not views:
        # The model chose to answer before any fetch (or the very first
        # decision was capped, which can't happen on step 1 with max_fetches
        # >= 1, but guard anyway). There is no data to answer from — surface
        # a clean PipelineError rather than calling the answer stage with
        # nothing, same "degrade to a caught error" stance as
        # orchestrator._answer_from_context.
        raise AnswerError(
            "The investigation ended without fetching any data, so there's "
            "nothing to answer from. Try rephrasing the question."
        )

    if on_stage:
        on_stage("answer")

    answer = _answer_over_gathered(llm, query, views, gathered, on_token=on_token)
    return LoopResult(answer=answer, views=views, steps=steps)


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


def _answer_over_gathered(llm, query: str, views: list, gathered: list, *, on_token=None) -> AnswerResult:
    """Hand the accumulated frames to the existing answer stage.

    One gathered frame => the single-dataframe path (unchanged from V1's
    single-view answer). Several => the existing multi-frame path, with each
    frame carrying its provenance label (see `_provenance_label`) so the
    model knows how a drilled-down child relates to its parent.
    """
    if len(gathered) == 1:
        _, df = gathered[0]
        return smart_pandas.ask(df, query, llm, original_query=query, on_token=on_token)

    # sanitize_names takes (label, df) pairs and turns the provenance labels
    # into valid, collision-free exec() variable names — same call the V1
    # multi-view path uses.
    named = smart_pandas.sanitize_names(gathered)
    return smart_pandas.ask(named, query, llm, on_token=on_token)
