"""validate_plan() against the manual's own worked examples and broken variants.

The worked-example URLs are extracted directly from mrx_manual.md §12 rather
than hand-transcribed, so this test doubles as a regression check: if the
manual's examples and validation.py's rules ever drift apart, this fails.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from mrx import validation
from mrx.pipeline_errors import PlanValidationError

MANUAL_PATH = Path(__file__).resolve().parent.parent / "mrx" / "mrx_manual.md"


def _load_worked_example_urls() -> list[str]:
    text = MANUAL_PATH.read_text(encoding="utf-8")
    urls = re.findall(r'"url":\s*"(https://[^"]+)"', text)
    assert len(urls) == 8, f"expected 8 worked examples in the manual, found {len(urls)}"
    return urls


WORKED_EXAMPLE_URLS = _load_worked_example_urls()

# Example 6 ("EQ Delta Cash on NYEQ ... underlying and counterparty in rows")
# uses p1218=CritCptyCLC, which doesn't exist anywhere in row_selection.md —
# a known defect in the manual itself (typo'd or stale code), not a
# validator bug. validate_plan correctly rejects it; excluded here rather
# than weakening the validator to accept an unrecognized code.
KNOWN_MANUAL_DEFECT_INDEX = 5


@dataclass
class FakePlan:
    url: str
    confidence: float = 0.95
    needs_clarification: str = None
    intent: str = "test intent"
    SmartDF: str = "a valid rephrased question"


_VALID_WORKED_EXAMPLES = [
    url for i, url in enumerate(WORKED_EXAMPLE_URLS) if i != KNOWN_MANUAL_DEFECT_INDEX
]


@pytest.mark.parametrize("url", _VALID_WORKED_EXAMPLES, ids=range(len(_VALID_WORKED_EXAMPLES)))
def test_worked_examples_pass_validation(url):
    validation.validate_plan(FakePlan(url=url))


def test_known_manual_defect_example_is_correctly_rejected():
    # See KNOWN_MANUAL_DEFECT_INDEX above: p1218=CritCptyCLC is not a real code.
    defect_url = WORKED_EXAMPLE_URLS[KNOWN_MANUAL_DEFECT_INDEX]
    with pytest.raises(PlanValidationError, match="CritCptyCLC"):
        validation.validate_plan(FakePlan(url=defect_url))


def test_invented_risk_type_code_rejected():
    basic_snapshot = WORKED_EXAMPLE_URLS[0]
    bad_url = basic_snapshot.replace("p13=EQDELTACASH", "p13=MADE_UP_CODE")
    with pytest.raises(PlanValidationError, match="MADE_UP_CODE"):
        validation.validate_plan(FakePlan(url=bad_url))


def test_missing_mandatory_param_rejected():
    basic_snapshot = WORKED_EXAMPLE_URLS[0]
    bad_url = basic_snapshot.replace("&p28=2024-10-31", "")
    with pytest.raises(PlanValidationError, match="p28"):
        validation.validate_plan(FakePlan(url=bad_url))


def test_low_confidence_rejected():
    with pytest.raises(PlanValidationError, match="Confidence"):
        validation.validate_plan(FakePlan(url=WORKED_EXAMPLE_URLS[0], confidence=0.4))


def test_needs_clarification_rejected():
    plan = FakePlan(url=WORKED_EXAMPLE_URLS[0], needs_clarification="Which node?")
    with pytest.raises(PlanValidationError, match="Which node"):
        validation.validate_plan(plan)


def test_empty_smartdf_rejected():
    plan = FakePlan(url=WORKED_EXAMPLE_URLS[0], SmartDF="   ")
    with pytest.raises(PlanValidationError, match="SmartDF"):
        validation.validate_plan(plan)


def test_p1079_not_enforced_despite_table_marking_it_mandatory():
    # multirow_parameters.md marks p1079 Mandatory, but no worked example includes
    # it. See MANDATORY_EXCEPTIONS in validation.py — this is a deliberate carve-out.
    assert "p1079" not in validation.load_mandatory_params()


def test_load_mandatory_params_matches_manual_examples():
    assert validation.load_mandatory_params() == {"p1", "p1021", "p1029", "p1217", "p27", "p28"}
