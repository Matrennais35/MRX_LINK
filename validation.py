"""
Post-hoc validation of an MRXPlan against the MRX manual's own rules:
never invent a code, never drop a mandatory param.

This does not change how the LLM builds the URL — it only checks the
result before we act on it (fetch data from production MRX). Mandatory
params are derived from multirow_parameters.md's own Validation column,
so this stays in sync with the table rather than a hand-maintained list.
"""

from pathlib import Path
from urllib.parse import urlparse, parse_qsl

from pipeline_errors import PlanValidationError

BASE_DIR = Path(__file__).resolve().parent
TABLES_DIR = BASE_DIR / "tables"

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


def load_mandatory_params() -> set[str]:
    """Param ids (e.g. "p1") marked `Mandatory` in multirow_parameters.md."""
    path = TABLES_DIR / "multirow_parameters.md"
    if not path.exists():
        raise PlanValidationError(f"MRX reference table not found at {path}")

    mandatory: set[str] = set()
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
        param_id, validation = cells[0], cells[3]
        if validation == "Mandatory" and param_id.isdigit():
            mandatory.add(f"p{param_id}")
    return mandatory - MANDATORY_EXCEPTIONS


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


def load_code_tables() -> dict[str, set[str]]:
    """Legal values per coded param, keyed by param id (e.g. "p13")."""
    risk_types = _parse_code_table(
        TABLES_DIR / "risk_type_selection.md", value_column="second"
    )
    row_codes = _parse_code_table(
        TABLES_DIR / "row_selection.md", value_column="second"
    )
    column_names = _parse_code_table(
        TABLES_DIR / "columns_selection.md", value_column="first"
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
