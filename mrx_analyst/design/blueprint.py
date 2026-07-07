"""The Blueprint — the per-question contract, the vision's central artifact.

The Designer instantiates the gold-standard PRINCIPLES into THIS question's
bar: sections as quality contracts (what each must establish), the data that
feeds them, and the fetches to run. Strict-schema-safe (no free-form dicts —
a real live 400 taught us).

MUTABILITY RULE (settled in the plan): this is a contract of QUALITIES, not a
frozen structure. The Executor may amend sections in-flight with traced
reasons; the one bounded Designer re-call is reserved for fetch-strategy
overhaul; a slot may be unfilled only when its data is genuinely unavailable
after attempts, with the reason.
"""

from typing import List

from pydantic import BaseModel, Field


class SectionSpec(BaseModel):
    title: str = Field(description="short section heading, e.g. 'The path', 'Drivers'")
    must_establish: str = Field(
        description="the QUALITY CONTRACT: what this section must establish, "
        "specific and checkable (e.g. 'the dated jumps that explain the net "
        "move, reconciled to it')"
    )
    data_needed: str = Field(
        description="what data feeds it, plain language (ties to a fetch or "
        "to already-available data)"
    )
    artifact: str = Field(
        description='how it is shown: "line chart" | "table" | "ranked bar" | '
        '"ranked bar + table" | "waterfall" | "none" (prose-only)'
    )


class FetchSpec(BaseModel):
    request: str = Field(
        description="the data request in NATURAL LANGUAGE for the fetch tool "
        "(it builds and validates the MRX URL itself), e.g. 'daily total FX "
        "Vega on GFXOPEMK, history dates, trailing month'"
    )
    when: str = Field(
        default="now",
        description='"now" for independent fetches, or "after: <section '
        'title>" when its parameters depend on what an earlier section shows '
        "(e.g. drilling the dominant pair)",
    )


class Blueprint(BaseModel):
    target: str = Field(description="the question behind the words — what the user needs")
    sections: List[SectionSpec] = Field(
        default_factory=list,
        description="the note's sections, in order — ONLY the sections this "
        "question earns (a lookup gets one; never pad)",
    )
    fetches: List[FetchSpec] = Field(
        default_factory=list,
        description="the MRX data requests that fill the sections; minimal — "
        "every fetch is a budgeted call into a production system",
    )
    clarification: str = Field(
        default="",
        description="NON-EMPTY ONLY when the question is too ambiguous to "
        "proceed and no sensible default exists: the ONE question to ask the "
        "user back. Everything else is then ignored.",
    )

    def render_text(self) -> str:
        """The blueprint as readable text — for the Executor's checklist, the
        Critic's rubric, the UI, and blueprint reviews."""
        if self.clarification:
            return f"CLARIFICATION NEEDED: {self.clarification}"
        lines = [f"TARGET: {self.target}", "", "SECTIONS:"]
        for i, s in enumerate(self.sections, 1):
            lines.append(f"{i}. [{s.title}] must establish: {s.must_establish}")
            lines.append(f"   data: {s.data_needed} | shown as: {s.artifact}")
        lines.append("")
        lines.append("FETCHES:")
        for f in self.fetches:
            lines.append(f"- ({f.when}) {f.request}")
        return "\n".join(lines)
