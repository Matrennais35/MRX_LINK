"""Durable, addressable storage for every dataframe the pipeline fetches.

A team-wide shared store (confirmed with the user: no per-analyst privacy
needed, this app has no per-user identity today). Every row still carries a
`session_id` so a later "reuse" decision (see router.py, phase 2) can rank
this conversation's own recent fetches ahead of the wider shared store,
without needing a schema migration when that phase lands.

SQLite holds metadata (one row per dataset); the actual dataframe is stored
as a Parquet file on disk, named by dataset id. Parquet over CSV/JSON here
because it round-trips dtypes exactly — a stored int64/float64/datetime
column must come back as the same dtype, not get inferred back to object.
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from .generate_link import MRXPlan

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_DIR = BASE_DIR / ".mrx_catalog"
DB_PATH = CATALOG_DIR / "catalog.sqlite3"
DATA_DIR = CATALOG_DIR / "data"


@dataclass
class Dataset:
    id: str
    session_id: str
    query: str
    plan: MRXPlan
    created_at: str
    description: str
    schema: dict  # {column_name: dtype_str}


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                query TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                description TEXT NOT NULL,
                schema_json TEXT NOT NULL
            )
            """
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
    id_, session_id, query, plan_json, created_at, description, schema_json = row
    return Dataset(
        id=id_,
        session_id=session_id,
        query=query,
        plan=MRXPlan.model_validate_json(plan_json),
        created_at=created_at,
        description=description,
        schema=json.loads(schema_json),
    )


def new_dataset_id() -> str:
    return f"ds_{uuid.uuid4().hex}"


def save(dataset: Dataset, df: pd.DataFrame) -> None:
    """Persist a dataset's metadata (SQLite) and its dataframe (Parquet)."""
    _ensure_storage()
    df.to_parquet(DATA_DIR / f"{dataset.id}.parquet")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO datasets (id, session_id, query, plan_json, created_at, description, schema_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset.id,
                dataset.session_id,
                dataset.query,
                dataset.plan.model_dump_json(),
                dataset.created_at,
                dataset.description,
                json.dumps(dataset.schema),
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
            "SELECT id, session_id, query, plan_json, created_at, description, schema_json "
            "FROM datasets WHERE id = ?",
            (dataset_id,),
        ).fetchone()
    return _row_to_dataset(row) if row else None


def list_all(*, session_id: str) -> list:
    """Every stored dataset's metadata (no dataframes), ranked so this
    session's own datasets come first (most recent first), then the rest
    of the shared store (most recent first) — never a flat unordered list,
    since a later "reuse" decision should prefer this conversation's own
    recent fetches over an unrelated analyst's dataset that happens to
    match on schema alone.
    """
    _ensure_storage()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, session_id, query, plan_json, created_at, description, schema_json "
            "FROM datasets ORDER BY created_at DESC"
        ).fetchall()

    datasets = [_row_to_dataset(row) for row in rows]
    own = [d for d in datasets if d.session_id == session_id]
    others = [d for d in datasets if d.session_id != session_id]
    return own + others
