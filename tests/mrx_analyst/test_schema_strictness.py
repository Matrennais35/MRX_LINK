"""Every agent Output schema must be strict-mode-safe: OpenAI's structured
output (json_schema, strict) rejects any object node without declared
properties (a free-form Dict) — a real live 400. This walks every agent
schema and fails on strict-incompatible nodes, so the bug class can't recur.
"""

from mrx_analyst.agents.analyst import AnalysisSpec
from mrx_analyst.agents.critic import Critique
from mrx_analyst.agents.datascout import MultiFetchPlan
from mrx_analyst.agents.planner import AnalysisPlan

AGENT_SCHEMAS = [AnalysisPlan, MultiFetchPlan, AnalysisSpec, Critique]


def _object_nodes(node, path=""):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield path, node
        for key, value in node.items():
            yield from _object_nodes(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _object_nodes(item, f"{path}[{i}]")


def test_no_agent_schema_contains_a_free_form_object():
    for model in AGENT_SCHEMAS:
        schema = model.model_json_schema()
        for path, node in _object_nodes(schema):
            # A typed model has "properties"; a free-form Dict has neither
            # properties nor additionalProperties=False — strict mode rejects it.
            assert "properties" in node or node.get("additionalProperties") is False, (
                f"{model.__name__} has a strict-incompatible free-form object at "
                f"{path or '<root>'} — use a typed model or a JSON-string field"
            )
