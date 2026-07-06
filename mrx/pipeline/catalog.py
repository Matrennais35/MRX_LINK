"""Durable, addressable storage for every dataframe the pipeline fetches,
plus the conversation history (questions + narrated answers) built on top
of it.

A team-wide shared store (confirmed with the user: no per-analyst privacy
needed, this app has no per-user identity today). Every dataset row
carries a `session_id` AND a `conversation_id` — see the note below on why
both exist, rather than just one.

SQLite holds metadata (one row per dataset); the actual dataframe is stored
as a Parquet file on disk, named by dataset id. Parquet over CSV/JSON here
because it round-trips dtypes exactly — a stored int64/float64/datetime
column must come back as the same dtype, not get inferred back to object.

`session_id` (Streamlit's own per-browser-tab id) and `conversation_id`
(see the `conversations`/`turns` tables below) are deliberately different
identifiers: `session_id` resets on every page refresh/new tab, while
`conversation_id` is generated once and kept in the browser's URL (a query
param), so the tab can be bookmarked/reopened and still find its own
history. A dataset is tagged with BOTH:
- `conversation_id` is what `router.find_reusable_dataset` and the
  conversation-context seeding (see loop.py) actually keys lookups on —
  "the data behind this conversation" must still be found after a refresh
  or after reopening a saved conversation from the sidebar, exactly like
  the turns it was fetched to help answer.
- `session_id` is kept alongside for `list_all`'s ranking (this session's
  *other*, not-yet-in-this-conversation fetches still rank ahead of the
  wider team-wide store) and because it's the natural scoping key for
  future features that aren't conversation-specific (e.g. "everything I've
  fetched today" across several conversations in one browser tab).
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from .models import MRXPlan

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CATALOG_DIR = BASE_DIR / ".mrx_catalog"
DB_PATH = CATALOG_DIR / "catalog.sqlite3"
DATA_DIR = CATALOG_DIR / "data"
# Rendered chart images (PNG), one per turn that produced a chart — so a plot
# survives a refresh/reopen. A matplotlib Figure can't go in SQLite, but its
# rendered PNG can live on disk (same split as datasets: metadata in SQLite,
# the heavy payload as a file), keyed by turn id.
CHARTS_DIR = CATALOG_DIR / "charts"


@dataclass
class Dataset:
    id: str
    session_id: str
    # Which conversation this fetch belongs to — see the module docstring
    # for why this is separate from session_id. Required, not optional:
    # find_reusable_dataset and the answer-from-context path both key on
    # this, so a dataset saved without it would be invisible to both no
    # matter how well it otherwise matches.
    conversation_id: str
    # `query` and `description` are free text (the analyst's own question,
    # and an LLM-written one-sentence summary of it) stored in a TEAM-WIDE
    # shared store. Today, nothing reads either field back into an LLM
    # prompt or executed code for ANY session other than the one that wrote
    # it (router.find_reusable_dataset only ever compares `.plan.url`
    # params, never these). If a future change starts feeding another
    # session's stored `query`/`description` into a prompt or exec()
    # namespace (e.g. a smarter multi-view synthesis step), that's a
    # cross-analyst prompt-injection surface worth treating carefully —
    # one analyst's phrasing becoming untrusted input to another's LLM
    # call. Not a problem today; flagged so it isn't wired in casually.
    query: str
    plan: MRXPlan
    created_at: str
    description: str
    schema: Optional[dict] = None  # {column_name: dtype_str} — see save()


@dataclass
class Turn:
    """One question-and-answer exchange within a conversation.

    Deliberately does NOT store the answer's full `value` for "dataframe"/
    "chart" typed results — a matplotlib Figure isn't serializable into a
    SQLite column, and a full dataframe can be arbitrarily large. Those
    result types instead carry `value_preview` (a short human-readable
    note, e.g. "table with 42 rows" or "chart: FX Vega evolution"). The
    underlying fetched data isn't lost — it's still in the `datasets` table
    via the normal reuse mechanism — only the rendered table/chart itself
    isn't replayed when a past conversation is reopened. "number"/"string"
    results ARE fully replayable: `value_preview` holds the actual value.
    """
    id: str
    conversation_id: str
    created_at: str
    question: str
    narration: str
    method: str
    answer_type: str  # "number" | "string" | "dataframe" | "chart"
    value_preview: str
    code: str


@dataclass
class StepTrace:
    """One recorded step of a controller-loop investigation — the "why
    each fetch happened" audit chain (see mrx/pipeline/loop.py and
    docs/agent_loop_design.md). Persisted per turn, keyed on `turn_id`, so a
    reviewer can reconstruct not just what data an answer used but the
    reasoning that led to each fetch.

    A turn with no recorded steps (e.g. one answered purely from cached
    context) simply has no rows here — this table is additive.
    """
    id: str
    turn_id: str
    conversation_id: str
    step_num: int
    action: str  # "fetch" | "answer"
    reasoning: str
    fetch_query: str
    # How a fetch step resolved — mirrors loop.StepRecord's fields, so the
    # persisted trace records fresh-fetch vs. reuse, and whether the hard cap
    # fired on a step where the model wanted more data.
    fetched_label: str
    reused_dataset_id: str
    capped: bool


@dataclass
class ConversationSummary:
    """One row per distinct conversation_id in the `turns` table — enough
    to render a "past conversations" list without loading every turn's
    full content. There's no dedicated `conversations` table: a
    conversation is just whatever conversation_id appears on 1+ turns, so
    this is derived from `turns` by GROUP BY rather than tracked separately
    (nothing else needs a conversation to exist before its first turn is
    saved).
    """
    conversation_id: str
    first_question: str
    turn_count: int
    last_activity_at: str


def new_conversation_id() -> str:
    return f"conv_{uuid.uuid4().hex}"


def new_turn_id() -> str:
    return f"turn_{uuid.uuid4().hex}"


def new_step_id() -> str:
    return f"step_{uuid.uuid4().hex}"


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                query TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                description TEXT NOT NULL,
                schema_json TEXT NOT NULL
            )
            """
        )
        # Every reuse check calls list_all(), which filters/sorts by these
        # two columns — without an index this is a full table scan on every
        # single view fetch. Cheap to add now, before a team-wide store
        # accumulates enough rows for it to matter.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_datasets_session_created "
            "ON datasets (session_id, created_at)"
        )
        # The answer-from-context path and find_reusable_dataset's primary
        # lookup key on conversation_id, not session_id (see the module
        # docstring) — same full-table-scan concern as the index above.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_datasets_conversation_created "
            "ON datasets (conversation_id, created_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                question TEXT NOT NULL,
                narration TEXT NOT NULL,
                method TEXT NOT NULL,
                answer_type TEXT NOT NULL,
                value_preview TEXT NOT NULL,
                code TEXT NOT NULL
            )
            """
        )
        # Every conversation reopen calls list_turns(), filtered by
        # conversation_id and ordered by created_at — same reasoning as the
        # datasets index above.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_turns_conversation_created "
            "ON turns (conversation_id, created_at)"
        )
        # The per-turn step trace (the "why each fetch happened" audit
        # chain). One row per loop step, keyed on turn_id. Additive: a turn
        # with no recorded steps simply has no rows here.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS steps (
                id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                step_num INTEGER NOT NULL,
                action TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                fetch_query TEXT NOT NULL,
                fetched_label TEXT NOT NULL,
                reused_dataset_id TEXT NOT NULL,
                capped INTEGER NOT NULL
            )
            """
        )
        # The trace is read back per turn (to render "how was this computed")
        # ordered by step_num — index the lookup key, same reasoning as the
        # turns index above.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_steps_turn_stepnum "
            "ON steps (turn_id, step_num)"
        )


@contextmanager
def _connect():
    # sqlite3.Connection used directly as a context manager only commits/
    # rolls back the transaction on exit — it does NOT close the connection,
    # which would leak a file handle per call. Wrap it so every caller's
    # `with _connect() as conn:` both commits and closes.
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _row_to_dataset(row: tuple) -> Dataset:
    id_, session_id, conversation_id, query, plan_json, created_at, description, schema_json = row
    return Dataset(
        id=id_,
        session_id=session_id,
        conversation_id=conversation_id,
        query=query,
        plan=MRXPlan.model_validate_json(plan_json),
        created_at=created_at,
        description=description,
        schema=json.loads(schema_json),
    )


def new_dataset_id() -> str:
    return f"ds_{uuid.uuid4().hex}"


def save(dataset: Dataset, df: pd.DataFrame) -> None:
    """Persist a dataset's metadata (SQLite) and its dataframe (Parquet).

    `dataset.schema` is derived from `df` here if not already set, rather
    than requiring every caller to independently replicate the same
    `{col: str(dtype) ...}` comprehension — this is the one place that
    actually has `df` in scope for the write, so it's the natural single
    source of truth for how a dataset's schema is computed. A caller MAY
    still pass its own `schema`, but there's no current need to.
    """
    schema = dataset.schema if dataset.schema is not None else {
        col: str(dtype) for col, dtype in df.dtypes.items()
    }
    _ensure_storage()
    df.to_parquet(DATA_DIR / f"{dataset.id}.parquet")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO datasets (id, session_id, conversation_id, query, plan_json, created_at, description, schema_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset.id,
                dataset.session_id,
                dataset.conversation_id,
                dataset.query,
                dataset.plan.model_dump_json(),
                dataset.created_at,
                dataset.description,
                json.dumps(schema),
            ),
        )


def load_df(dataset_id: str) -> pd.DataFrame:
    """Load a previously-saved dataset's dataframe from disk."""
    path = DATA_DIR / f"{dataset_id}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No stored dataset with id {dataset_id!r}")
    return pd.read_parquet(path)


def get(dataset_id: str) -> Optional[Dataset]:
    """Look up a single dataset's metadata by id, or None if it doesn't exist."""
    _ensure_storage()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, session_id, conversation_id, query, plan_json, created_at, description, schema_json "
            "FROM datasets WHERE id = ?",
            (dataset_id,),
        ).fetchone()
    return _row_to_dataset(row) if row else None


def list_all(*, session_id: str, conversation_id: Optional[str] = None) -> list:
    """Every stored dataset's metadata (no dataframes), ranked so this
    conversation's own datasets come first (most recent first), then this
    session's other datasets, then the rest of the shared store (most
    recent first) — never a flat unordered list, since a later "reuse"
    decision should prefer this exact conversation's recent fetches over
    an unrelated question (even in the same browser session) that happens
    to match on schema alone.

    `conversation_id` is optional (defaults to no conversation-level
    boost) for callers that only care about session-wide ranking — e.g.
    the sidebar's "recently fetched data" panel, which intentionally shows
    activity across the whole session, not just the active conversation.

    The ranking is done in SQL (each comparison sorts False/0 before
    True/1) rather than fetching everything and re-sorting in Python —
    lets the `idx_datasets_conversation_created`/`idx_datasets_session_created`
    indexes actually serve the query instead of only being usable for a
    plain WHERE.
    """
    _ensure_storage()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, session_id, conversation_id, query, plan_json, created_at, description, schema_json "
            "FROM datasets ORDER BY (conversation_id != ?), (session_id != ?), created_at DESC",
            (conversation_id or "", session_id),
        ).fetchall()

    return [_row_to_dataset(row) for row in rows]


def list_for_conversation(*, conversation_id: str) -> list:
    """Every dataset fetched within one conversation, most recent first —
    used by the loop's conversation-context seeding (see loop.py) and
    router.find_reusable_dataset, both of which need "this conversation's
    data" specifically, not the whole team-wide store `list_all` returns
    (just ranked). Filtering in SQL rather than slicing list_all()'s output
    so this scales with the size of one conversation, not the whole catalog.
    """
    _ensure_storage()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, session_id, conversation_id, query, plan_json, created_at, description, schema_json "
            "FROM datasets WHERE conversation_id = ? ORDER BY created_at DESC",
            (conversation_id,),
        ).fetchall()

    return [_row_to_dataset(row) for row in rows]


def _row_to_turn(row: tuple) -> Turn:
    id_, conversation_id, created_at, question, narration, method, answer_type, value_preview, code = row
    return Turn(
        id=id_, conversation_id=conversation_id, created_at=created_at, question=question,
        narration=narration, method=method, answer_type=answer_type,
        value_preview=value_preview, code=code,
    )


def save_turn(turn: Turn) -> None:
    """Persist one conversation turn (question + narrated answer)."""
    _ensure_storage()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO turns (id, conversation_id, created_at, question, narration, method, answer_type, value_preview, code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn.id, turn.conversation_id, turn.created_at, turn.question,
                turn.narration, turn.method, turn.answer_type, turn.value_preview, turn.code,
            ),
        )


def save_turn_image(turn_id: str, png_bytes: bytes) -> None:
    """Persist a turn's rendered chart as a PNG on disk, keyed by turn id, so
    the plot survives a refresh/reopen. Kept out of the SQLite row (a Figure
    isn't storable there, and a PNG is a heavy blob) — same metadata-in-SQLite,
    payload-on-disk split as datasets. No table change: presence is checked by
    file existence (see load_turn_image / turn_image_path).
    """
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    (CHARTS_DIR / f"{turn_id}.png").write_bytes(png_bytes)


def turn_image_path(turn_id: str):
    """The path to a turn's stored chart PNG if one exists, else None."""
    path = CHARTS_DIR / f"{turn_id}.png"
    return path if path.exists() else None


def load_turn_image(turn_id: str):
    """A turn's stored chart PNG bytes, or None if it has no saved image."""
    path = turn_image_path(turn_id)
    return path.read_bytes() if path else None


def list_turns(*, conversation_id: str) -> list:
    """Every turn in one conversation, oldest first (the natural reading
    order for replaying a conversation thread).
    """
    _ensure_storage()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, conversation_id, created_at, question, narration, method, answer_type, value_preview, code "
            "FROM turns WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()

    return [_row_to_turn(row) for row in rows]


def _row_to_step(row: tuple) -> StepTrace:
    (id_, turn_id, conversation_id, step_num, action, reasoning,
     fetch_query, fetched_label, reused_dataset_id, capped) = row
    return StepTrace(
        id=id_, turn_id=turn_id, conversation_id=conversation_id, step_num=step_num,
        action=action, reasoning=reasoning, fetch_query=fetch_query,
        fetched_label=fetched_label, reused_dataset_id=reused_dataset_id,
        capped=bool(capped),
    )


def save_steps(steps: list) -> None:
    """Persist a turn's full step trace (a list of StepTrace) in one
    transaction. A no-op for an empty list, so callers can call
    it unconditionally without branching on whether the loop ran.
    """
    if not steps:
        return
    _ensure_storage()
    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO steps (id, turn_id, conversation_id, step_num, action, reasoning,
                               fetch_query, fetched_label, reused_dataset_id, capped)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (s.id, s.turn_id, s.conversation_id, s.step_num, s.action, s.reasoning,
                 s.fetch_query, s.fetched_label, s.reused_dataset_id, int(s.capped))
                for s in steps
            ],
        )


def list_steps(*, turn_id: str) -> list:
    """Every recorded step for one turn, in decision order (step_num asc) —
    the audit chain rendered under a past answer's "how was this computed".
    """
    _ensure_storage()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, turn_id, conversation_id, step_num, action, reasoning, "
            "fetch_query, fetched_label, reused_dataset_id, capped "
            "FROM steps WHERE turn_id = ? ORDER BY step_num ASC",
            (turn_id,),
        ).fetchall()

    return [_row_to_step(row) for row in rows]


def list_conversations(*, limit: int = 30) -> list:
    """Summaries of the most recently active conversations, most recent
    first — team-wide, same "no per-analyst privacy" stance as `list_all`
    (see catalog.py's module docstring): this app has no per-user identity
    today, so there's no principled way to show "your" conversations only.
    """
    _ensure_storage()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT conversation_id,
                   (SELECT question FROM turns t2
                    WHERE t2.conversation_id = t1.conversation_id
                    ORDER BY t2.created_at ASC LIMIT 1) AS first_question,
                   COUNT(*) AS turn_count,
                   MAX(created_at) AS last_activity_at
            FROM turns t1
            GROUP BY conversation_id
            ORDER BY last_activity_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        ConversationSummary(
            conversation_id=r[0], first_question=r[1], turn_count=r[2], last_activity_at=r[3],
        )
        for r in rows
    ]
