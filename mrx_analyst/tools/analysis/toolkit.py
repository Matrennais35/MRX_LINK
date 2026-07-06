"""Tool adapters over the tested ops — what the Analyst agent proposes.

Each adapter's Args is a pydantic model over an EVIDENCE LABEL + column names,
so a bad proposal (wrong label, missing column) becomes a structured error fed
back to the agent, not a stack trace. The ops themselves live in ops.py /
charts.py and are golden-tested; adapters only resolve + validate + delegate.
"""

from typing import List, Optional

import pandas as pd
from pydantic import BaseModel, Field

from ...core.context import RunContext
from ...core.tool import Tool, ToolResult
from . import charts, ops


def _resolve(ctx: RunContext, label: str) -> pd.DataFrame:
    for ev in ctx.evidence:
        if ev.label == label:
            return ev.df
    raise ValueError(
        f"no evidence labelled {label!r} — available: {[e.label for e in ctx.evidence]}"
    )


def _resolve_value_col(ctx: RunContext, label: str, value_col: Optional[str]) -> str:
    if value_col:
        return value_col
    for ev in ctx.evidence:
        if ev.label == label and getattr(ev.profile, "value_columns", None):
            return ev.profile.value_columns[0]
    raise ValueError(f"value_col not given and none detected for {label!r}")


def _require_columns(df: pd.DataFrame, cols: List[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"columns not in the data: {missing} — available: {list(df.columns)[:20]}")


class AttributionTool(Tool):
    name = "attribution"
    description = ("Signed contribution of each group to the net move of a value column "
                   "— the computation behind every 'what drove X' answer. Returns a ranked "
                   "table with contribution and share_of_net.")

    class Args(BaseModel):
        dataset: str = Field(description="evidence label to compute over")
        group_cols: List[str] = Field(description="column(s) to attribute by, e.g. ['Book']")
        value_col: Optional[str] = Field(None, description="measure column; auto-detected if omitted")
        top_n: int = 10

    def run(self, args: "AttributionTool.Args", ctx: RunContext) -> ToolResult:
        df = _resolve(ctx, args.dataset)
        value_col = _resolve_value_col(ctx, args.dataset, args.value_col)
        _require_columns(df, args.group_cols + [value_col])
        table = ops.attribution(df, args.group_cols, value_col, args.top_n)
        return ToolResult(
            value=table,
            summary=f"attribution of {value_col} by {'+'.join(args.group_cols)}: top {len(table)} groups",
            audit={"args": args.model_dump(), "net": float(table['contribution'].sum())},
        )


class VarianceTool(Tool):
    name = "variance"
    description = ("Two-period delta by group over Current/Previous columns (the MRX "
                   "compare-with-T-1 frame shape). Returns current/previous/delta/pct_change ranked by |delta|.")

    class Args(BaseModel):
        dataset: str
        group_cols: List[str]
        current_col: str
        previous_col: str
        top_n: int = 10

    def run(self, args: "VarianceTool.Args", ctx: RunContext) -> ToolResult:
        df = _resolve(ctx, args.dataset)
        _require_columns(df, args.group_cols + [args.current_col, args.previous_col])
        table = ops.variance(df, args.group_cols, args.current_col, args.previous_col, args.top_n)
        return ToolResult(
            value=table,
            summary=f"variance by {'+'.join(args.group_cols)}: top {len(table)} deltas",
            audit={"args": args.model_dump()},
        )


class ConcentrationTool(Tool):
    name = "concentration"
    description = ("How concentrated |value| is across a grouping: HHI, top-1/top-5 share "
                   "and the ranked share table — the 'one big position or many small ones' check.")

    class Args(BaseModel):
        dataset: str
        group_col: str
        value_col: Optional[str] = None

    def run(self, args: "ConcentrationTool.Args", ctx: RunContext) -> ToolResult:
        df = _resolve(ctx, args.dataset)
        value_col = _resolve_value_col(ctx, args.dataset, args.value_col)
        _require_columns(df, [args.group_col, value_col])
        result = ops.concentration(df, args.group_col, value_col)
        return ToolResult(
            value=result,
            summary=(f"concentration of {value_col} by {args.group_col}: "
                     f"HHI {result['hhi']:.2f}, top-1 {result['top1_share']:.0%}"),
            audit={"args": args.model_dump(), "hhi": result["hhi"]},
        )


class WaterfallChartTool(Tool):
    name = "waterfall_chart"
    description = ("Contribution waterfall from a label column + value column of an evidence "
                   "table (typically the attribution output) — the canonical attribution picture.")

    class Args(BaseModel):
        dataset: str
        label_col: str
        value_col: str
        title: str = ""

    def run(self, args: "WaterfallChartTool.Args", ctx: RunContext) -> ToolResult:
        df = _resolve(ctx, args.dataset)
        _require_columns(df, [args.label_col, args.value_col])
        fig = charts.waterfall(df[args.label_col].astype(str).tolist(),
                               df[args.value_col].astype(float).tolist(), args.title)
        return ToolResult(value=fig, summary=f"waterfall of {args.value_col} by {args.label_col}",
                          audit={"args": args.model_dump()})


class RankedBarChartTool(Tool):
    name = "ranked_bar_chart"
    description = "Signed horizontal ranking chart from a label column + value column."

    class Args(BaseModel):
        dataset: str
        label_col: str
        value_col: str
        title: str = ""

    def run(self, args: "RankedBarChartTool.Args", ctx: RunContext) -> ToolResult:
        df = _resolve(ctx, args.dataset)
        _require_columns(df, [args.label_col, args.value_col])
        fig = charts.ranked_bar(df[args.label_col].astype(str).tolist(),
                                df[args.value_col].astype(float).tolist(), args.title)
        return ToolResult(value=fig, summary=f"ranked bar of {args.value_col} by {args.label_col}",
                          audit={"args": args.model_dump()})


class EvolutionChartTool(Tool):
    name = "evolution_chart"
    description = ("A series over time from an x (dates) column + y column — for "
                   "trend/evolution questions. For wide MRX frames, melt first (codegen) or "
                   "pass the date columns' totals via a prepared table.")

    class Args(BaseModel):
        dataset: str
        x_col: str
        y_col: str
        title: str = ""
        ylabel: str = ""

    def run(self, args: "EvolutionChartTool.Args", ctx: RunContext) -> ToolResult:
        df = _resolve(ctx, args.dataset)
        _require_columns(df, [args.x_col, args.y_col])
        fig = charts.evolution(df[args.x_col].tolist(), df[args.y_col].astype(float).tolist(),
                               args.title, args.ylabel)
        return ToolResult(value=fig, summary=f"evolution of {args.y_col} over {args.x_col}",
                          audit={"args": args.model_dump()})


class TrendTool(Tool):
    name = "trend"
    description = ("Characterize a daily series from a wide History-dates frame: start/end/"
                   "net/pct, the top daily moves WITH DATES (the answer's 'when did it "
                   "happen'), and phases. Registers the long series as evidence "
                   "'trend_series' — chart it with evolution_chart(dataset='trend_series', "
                   "x_col='Date', y_col='Value'). Use for ANY fetched daily series.")

    class Args(BaseModel):
        dataset: str = Field(description="evidence label of a wide date-columns frame")
        top_jumps: int = 3

    def run(self, args: "TrendTool.Args", ctx: RunContext) -> ToolResult:
        df = _resolve(ctx, args.dataset)
        result = ops.trend(df, top_jumps=args.top_jumps)
        return ToolResult(
            value=result,
            summary=(f"trend: {result['start']:,.0f} -> {result['end']:,.0f} "
                     f"(net {result['net']:,.0f}); largest daily move on {result['largest_jump_date']}"),
            audit={"args": args.model_dump(), "net": result["net"]},
        )


class PositionChangeTool(Tool):
    name = "position_change"
    description = ("Decompose a change into NEW positions (previous=0), CLOSED (current=0) "
                   "and EXISTING revaluation — the deterministic 'what kind of change was "
                   "this'. Needs a deal/position-level frame with current+previous columns "
                   "(two picked date columns work). Registers top contributors per bucket "
                   "as evidence 'position_detail'. Use for any deal-level change question.")

    class Args(BaseModel):
        dataset: str
        label_cols: List[str] = Field(description="position identifier column(s), e.g. ['Deal/Security']")
        current_col: str
        previous_col: str
        top_n: int = 5

    def run(self, args: "PositionChangeTool.Args", ctx: RunContext) -> ToolResult:
        df = _resolve(ctx, args.dataset)
        _require_columns(df, args.label_cols + [args.current_col, args.previous_col])
        result = ops.position_change(df, args.label_cols, args.current_col,
                                     args.previous_col, args.top_n)
        buckets = ", ".join(f"{row['bucket']}: {row['delta']:,.0f}"
                            for _, row in result["table"].iterrows())
        return ToolResult(
            value=result,
            summary=f"position change decomposition — {buckets}",
            audit={"args": args.model_dump(), "net": result["net"]},
        )


TOOLKIT = [
    AttributionTool(), VarianceTool(), ConcentrationTool(),
    TrendTool(), PositionChangeTool(),
    WaterfallChartTool(), RankedBarChartTool(), EvolutionChartTool(),
]


def toolkit_descriptions() -> str:
    """The toolkit menu injected into the Analyst's prompt: name, what it does,
    and its argument schema — the agent proposes calls against this."""
    lines = []
    for tool in TOOLKIT:
        fields = ", ".join(
            f"{name}: {f.annotation}" for name, f in tool.Args.model_fields.items()
        )
        lines.append(f"- {tool.name}({fields}): {tool.description}")
    return "\n".join(lines)
