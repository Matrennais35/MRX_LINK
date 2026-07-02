from mrx.pipeline.models import MRXPlan
from mrx.views.multirow.generate_link import get_link
from tests.conftest import FakeStructuredLLM

URL = (
    "https://market.risk.echonet/Market%20Risk%20Explorer/Market%20Risk%20Explorer.application"
    "?env=Production&viewid=6168&p1=EQDUSNLH"
)


def _plan(**overrides):
    defaults = dict(
        intent="test", view_reasoning="r", parameters="p", assumptions=[],
        confidence=0.95, needs_clarification=None, SmartDF="q", url=URL,
    )
    defaults.update(overrides)
    return MRXPlan(**defaults)


def test_get_link_returns_the_llm_plan():
    plan = _plan()
    llm = FakeStructuredLLM([plan])
    result = get_link(llm, "some query")
    assert result is plan


def test_prior_attempts_are_replayed_as_correction_messages():
    plan1, plan2 = _plan(intent="first try"), _plan(intent="second try")
    llm = FakeStructuredLLM([plan2])

    get_link(llm, "some query", prior_attempts=[(plan1, "p13='BAD' is not a recognized code")])

    messages = llm.calls[0]
    joined = " ".join(m.content for m in messages)
    assert "BAD" in joined
    assert "first try" in joined  # the rejected plan was replayed via model_dump_json()
