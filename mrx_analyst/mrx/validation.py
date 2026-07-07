"""
Post-hoc validation of an MRXPlan against the MRX manual's own rules:
never invent a code, never drop a mandatory param.

This does not change how the LLM builds the URL — it only checks the
result before we act on it (fetch data from production MRX). Mandatory
params are derived from multirow_parameters.md's own Validation column,
so this stays in sync with the table rather than a hand-maintained list.

`TABLES_DIR` and the individual table filenames are imported from
generate_link.py (which owns them, since they're primarily the LLM's
reference material) rather than redefined here — two independently
hardcoded copies previously had to be kept in sync by hand, and drifting
(e.g. adding a table to one but not the other) would silently defeat this
module's whole purpose: a coded param's hallucinated/stale value passing
validation because its legal-values table was never wired in here.
"""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse, parse_qsl

from . import generate_link
from ..common.errors import PlanValidationError

TABLES_DIR = generate_link.TABLES_DIR

# Every filename referenced below must be one generate_link.py also knows
# about (it builds the LLM's system prompt from generate_link.TABLE_FILES),
# checked once at import time rather than silently drifting if a table is
# ever renamed/removed from one list but not the other.
_MANDATORY_PARAMS_FILE = "multirow_parameters.md"
_RISK_TYPE_FILE = "risk_type_selection.md"
_ROW_SELECTION_FILE = "row_selection.md"
_COLUMNS_SELECTION_FILE = "columns_selection.md"
for _file in (_MANDATORY_PARAMS_FILE, _RISK_TYPE_FILE, _ROW_SELECTION_FILE, _COLUMNS_SELECTION_FILE):
    assert _file in generate_link.TABLE_FILES, (
        f"validation.py references {_file!r}, which is not in generate_link.TABLE_FILES — "
        f"the two modules' table lists have drifted out of sync"
    )

MRX_BASE_URL = (
    "https://market.risk.echonet/Market%20Risk%20Explorer/"
    "Market%20Risk%20Explorer.application"
)

# Row-level parameters, in order; only p1217 is mandatory per multirow_parameters.md.
ROW_LEVEL_PARAMS = ["p1217", "p1218", "p1219", "p1186", "p1759"]

# multirow_parameters.md marks p1079 (Counterparty Definition) Mandatory, but
# the manual's own §5 URL template and all 8 worked examples omit it — the
# table and the manual disagree. Until that's reconciled upstream, don't
# enforce it: doing so would reject every one of the manual's own examples.
MANDATORY_EXCEPTIONS = {"p1079"}


# Non-"pNNN" params the URL always carries that aren't rows in
# multirow_parameters.md's per-param table (they're structural to the MRX
# application itself, not a Multirow Risk Snapshot parameter).
_NON_PARAM_URL_KEYS = {"env", "viewid"}

# Params used in multiple of the manual's own worked examples (p1070, e.g.
# "p1070=No"; p1385, e.g. "p1385=Absolute" for cell-value display mode —
# see manual.md's Cell Value Display section) but genuinely absent from
# multirow_parameters.md's per-param table — a table/manual gap, same class
# of issue as MANDATORY_EXCEPTIONS above (p1079). Without this, the
# unknown-param check below would reject the manual's own examples, which
# is worse than the gap it's meant to close.
UNKNOWN_PARAM_EXCEPTIONS = {"p1070", "p1385"}


# These re-read and re-parse the same on-disk reference tables — content
# that never changes at runtime — on every call. validate_plan() is called
# once per attempt in _plan_and_validate's self-correction retry loop
# (potentially several times per view, several views per multi-fetch
# question), so uncached this was a dozen-ish redundant full file
# reads/parses for a single 3-view question with one retry each.
# lru_cache(maxsize=1) is safe because every caller treats the returned
# set/dict as read-only (see validate_plan below: only set-difference and
# dict.get, never in-place mutation of the cached object).


@lru_cache(maxsize=1)
def load_mandatory_params() -> set[str]:
    """Param ids (e.g. "p1") marked `Mandatory` in multirow_parameters.md."""
    mandatory: set[str] = set()
    for param_id, validation_value in _iter_param_table_rows():
        if validation_value == "Mandatory":
            mandatory.add(f"p{param_id}")
    return mandatory - MANDATORY_EXCEPTIONS


@lru_cache(maxsize=1)
def load_legal_param_names() -> set[str]:
    """Every `pNNN` name multirow_parameters.md recognizes at all (mandatory
    or optional) — the full param universe, not just the mandatory subset.
    """
    return {f"p{param_id}" for param_id, _ in _iter_param_table_rows()}


def _iter_param_table_rows():
    """Yield (param_id, validation_value) for every row of
    multirow_parameters.md's `| ID | Category | Label | Validation | ... |`
    table. Shared by load_mandatory_params and load_legal_param_names so
    both stay derived from the exact same parse of the exact same table.
    """
    path = TABLES_DIR / _MANDATORY_PARAMS_FILE
    if not path.exists():
        raise PlanValidationError(f"MRX reference table not found at {path}")

    in_table = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if set(cells[0]) <= {"-", ":"}:
            in_table = True
            continue
        if not in_table:
            continue
        param_id, validation_value = cells[0], cells[3]
        if param_id.isdigit():
            yield param_id, validation_value


@lru_cache(maxsize=None)
def _parse_code_table(path: Path, *, value_column: str) -> set[str]:
    """Parse a two-column `| Display Name | Code |` reference table.

    `value_column` is "first" to keep the Display Name column (used by
    p1029, whose URL value is the display name, not the internal code)
    or "second" to keep the Code column (used by p13 and the row tables).
    """
    if not path.exists():
        raise PlanValidationError(f"MRX reference table not found at {path}")

    values: set[str] = set()
    in_table = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if set(cells[0]) <= {"-", ":"}:  # the |---|---| separator row
            in_table = True
            continue
        if not in_table:
            continue  # header row, before the separator
        values.add(cells[0] if value_column == "first" else cells[1])
    return values


@lru_cache(maxsize=1)
def load_code_tables() -> dict[str, set[str]]:
    """Legal values per coded param, keyed by param id (e.g. "p13")."""
    risk_types = _parse_code_table(
        TABLES_DIR / _RISK_TYPE_FILE, value_column="second"
    )
    row_codes = _parse_code_table(
        TABLES_DIR / _ROW_SELECTION_FILE, value_column="second"
    )
    column_names = _parse_code_table(
        TABLES_DIR / _COLUMNS_SELECTION_FILE, value_column="first"
    )

    tables = {"p13": risk_types, "p1029": column_names}
    for param in ROW_LEVEL_PARAMS:
        tables[param] = row_codes
    return tables


def parse_mrx_url(url: str) -> dict[str, str]:
    """Split an MRX URL into its `{param: decoded value}` query parameters."""
    if not url or not url.startswith(MRX_BASE_URL):
        raise PlanValidationError(f"URL does not start with the expected MRX base URL: {url!r}")

    parsed = urlparse(url)
    if not parsed.query:
        raise PlanValidationError(f"URL has no query parameters: {url!r}")

    try:
        pairs = parse_qsl(parsed.query, strict_parsing=True)
    except ValueError as e:
        raise PlanValidationError(f"URL query string is malformed: {url!r}") from e

    return dict(pairs)


def validate_plan(plan, *, min_confidence: float = 0.7) -> None:
    """Raise PlanValidationError if `plan` should not be acted upon."""
    if plan.needs_clarification:
        raise PlanValidationError(plan.needs_clarification)

    if plan.confidence < min_confidence:
        raise PlanValidationError(
            f"Confidence {plan.confidence:.2f} is below the minimum {min_confidence:.2f}: "
            f"{plan.intent}"
        )

    if not plan.SmartDF.strip():
        raise PlanValidationError("SmartDF rephrasing is empty")

    params = parse_mrx_url(plan.url)

    unknown = params.keys() - load_legal_param_names() - _NON_PARAM_URL_KEYS - UNKNOWN_PARAM_EXCEPTIONS
    if unknown:
        raise PlanValidationError(f"URL has unrecognized parameters: {sorted(unknown)}")

    missing = load_mandatory_params() - params.keys()
    if missing:
        raise PlanValidationError(f"URL is missing mandatory parameters: {sorted(missing)}")

    code_tables = load_code_tables()
    for param, legal_values in code_tables.items():
        value = params.get(param)
        if value is None:
            continue  # optional row levels, or p13 omitted (e.g. file-search variant)
        if value not in legal_values:
            raise PlanValidationError(
                f"{param}={value!r} is not a recognized code (invented or stale value)"
            )
