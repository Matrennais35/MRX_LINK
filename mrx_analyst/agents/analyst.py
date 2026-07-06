"""The Analyst — turns evidence into Facts (numbers, zero prose).

Proposes an AnalysisSpec: toolkit operations first (typed, golden-tested,
deterministic — attribution/variance/concentration + chart builders), with
free-form pandas codegen as the DECLARED fallback for questions the toolkit
genuinely doesn't cover. The compute/interpret split is strict: the Analyst
produces the table/chart/metrics; the Narrator interprets them. (Evidence:
a model that computes and narrates in one call just transcribes the numbers.)

The Analyst reasons over evidence PROFILES, never raw frames — the profile is
what tells it which columns exist and where the mass/concentration is.
"""

from typing import Any, Dict, List, Optional

from dataclasses import dataclass, field

import pandas as pd
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from ..core.agent import Agent
from ..core.context import RunContext
from ..tools.analysis import toolkit_descriptions


class ToolkitCall(BaseModel):
    tool: str = Field(description="a toolkit tool name, exactly as listed")
    section: str = Field(
        default="",
        description="the report-outline section TITLE this op's output fills "
        "(exactly as in the outline); empty only when no outline was given",
    )
    # A JSON-encoded object string, NOT a free-form dict: OpenAI's strict
    # structured-output mode rejects schemas with arbitrary-key objects
    # (additionalProperties must be false) — a real live failure. The string is
    # parsed and validated against the tool's Args model at execution; bad JSON
    # or bad fields feed back into the corrective retry.
    args_json: str = Field(description="the tool's arguments as a JSON object string, "
                                       "e.g. '{\"dataset\": \"facts\", \"group_cols\": [\"Book\"]}'")


class AnalysisSpec(BaseModel):
    reasoning: str = Field(description="what to compute and why it serves the target")
    ops: List[ToolkitCall] = Field(
        default_factory=list,
        description="toolkit calls, in order. The FIRST table-producing op's output "
        "becomes the answer's table (and is registered as evidence label 'facts' so "
        "chart ops can reference it). Prefer the toolkit — it is tested and exact.",
    )
    fallback_code_request: Optional[str] = Field(
        None,
        description="When the toolkit can't express a needed computation (reshapes, "
        "hierarchy handling, multi-frame combines): a precise description for the "
        "code-generation step. It runs FIRST — its named output tables become "
        "evidence your ops can then reference. Leave null otherwise.",
    )
    fallback_section: str = Field(
        default="",
        description="the outline section the fallback's PRIMARY table/chart fills",
    )


ANALYST_SYSTEM_PROMPT = """\
You are the computation planner for a market-risk answer. Given the analysis
plan (target + representation), the available evidence datasets (as profiles:
columns, mass, concentration — you never see raw frames), and the toolkit
below, propose the operations that produce the FACTS the answer needs: the
table (the structured breakdown the numbers live in) and, when the plan's
representation calls for one, the chart.

THE TOOLKIT (prefer these — tested, exact, auditable):
{toolkit}

Rules:
- Reference datasets by their evidence label; reference columns exactly as the
  profiles list them. Each op's args_json is a JSON OBJECT STRING matching that
  tool's argument schema from the menu above.
- When a REPORT OUTLINE is given, tag every op (and the fallback) with the
  section title it fills, and make sure EVERY section's needs are served by
  some op or the fallback — a section left uncomputed becomes a visible gap
  in the user's report.
- The first table-producing op's output is registered as evidence label
  'facts' — point chart ops at 'facts' (e.g. waterfall over the attribution
  output's group/contribution columns).
- Serve the plan's REPRESENTATION: attribution -> attribution + waterfall_chart;
  top contributors -> attribution + ranked_bar_chart; a plain lookup may need
  no ops at all beyond what the profile already shows.
- For ANY fetched daily series, use `trend` (it dates the moves — never settle
  for an endpoint difference when the path was fetched), then chart
  evolution_chart over its 'trend_series' output.
- For ANY deal/position-level change, use `position_change` — whether the move
  is NEW positions vs. revaluation of existing ones is usually the real "why".
- Use fallback_code_request ONLY when the toolkit genuinely can't express the
  computation (e.g. a bespoke reshape) — describe it precisely; a code
  generator executes it against the raw frames.
- You produce numbers, never prose — interpretation happens elsewhere.
"""


@dataclass
class Facts:
    """What the computation produced — the anchored ground truth the Narrator
    interprets and the Critic checks against. `artifacts` carries every output
    in execution order, tagged with the outline section it fills (the
    structure-first contract); `table`/`chart` stay as the primary pair for
    simple answers and back-compat."""
    table: Optional[pd.DataFrame] = None
    chart: Optional[object] = None            # matplotlib Figure
    metrics: Dict[str, Any] = field(default_factory=dict)
    code: str = ""                            # codegen fallback's code, when used
    ops_summary: List[str] = field(default_factory=list)  # one line per executed op
    artifacts: List[Dict] = field(default_factory=list)   # {kind, title, section, obj}

    def add_artifact(self, kind: str, obj, *, title: str = "", section: str = "") -> None:
        self.artifacts.append({"kind": kind, "title": title, "section": section, "obj": obj})

    def render_text(self, max_rows: int = 25) -> str:
        """The Facts as text for the Narrator/Critic prompts — grouped by the
        outline section each artifact fills, so per-section prose/checking is
        grounded in per-section facts."""
        parts = []
        if self.metrics:
            parts.append("metrics: " + ", ".join(f"{k}={v}" for k, v in self.metrics.items()))
        sectioned_tables = [a for a in self.artifacts if a["kind"] == "table"]
        if sectioned_tables:
            for a in sectioned_tables:
                head = f"[section: {a['section']}] " if a["section"] else ""
                title = a["title"] or "computed table"
                df = a["obj"]
                parts.append(f"{head}{title} ({df.shape[0]}x{df.shape[1]}):\n"
                             + df.head(max_rows).to_string())
        elif self.table is not None:
            parts.append(f"computed table ({self.table.shape[0]}x{self.table.shape[1]}):\n"
                         + self.table.head(max_rows).to_string())
        charts = [a for a in self.artifacts if a["kind"] == "chart"]
        if charts:
            for a in charts:
                head = f"[section: {a['section']}] " if a["section"] else ""
                parts.append(f"{head}(chart produced: {a['title'] or 'figure'})")
        elif self.chart is not None:
            parts.append("(a chart was produced and is shown to the user)")
        if self.ops_summary:
            parts.append("operations: " + "; ".join(self.ops_summary))
        return "\n\n".join(parts) or "(no computation was needed)"


class Analyst(Agent):
    role = "analyst"
    Output = AnalysisSpec

    def __init__(self):
        self.system_prompt = ANALYST_SYSTEM_PROMPT.format(toolkit=toolkit_descriptions())

    def build_messages(self, ctx: RunContext) -> list:
        plan = ctx.plan
        profiles = "\n\n".join(
            f"[{e.label}] ({e.provenance}) — {e.plan.intent if e.plan else ''}\n{e.profile.render_text()}"
            for e in ctx.evidence
        ) or "(no evidence)"
        outline = ""
        if plan is not None and getattr(plan, "outline", None):
            outline = "\n\nREPORT OUTLINE (tag each op with the section it fills):\n" + "\n".join(
                f"- [{sec.title}] answers: {sec.section_question} | needs: {sec.needs} | shown as: {sec.artifact}"
                for sec in plan.outline
            )
        prior_error = getattr(ctx, "_analyst_error", "")
        error_block = (
            f"\n\nYOUR PREVIOUS PROPOSAL FAILED — fix exactly this and repropose:\n{prior_error}"
            if prior_error else ""
        )
        return [HumanMessage(content=(
            f"Question: {ctx.query}\n\n"
            f"Target: {plan.target if plan else ctx.query}\n"
            f"Representation the answer should use: {plan.representation if plan else 'best fit'}{outline}\n\n"
            f"EVIDENCE PROFILES:\n{profiles}{error_block}"
        ))]
