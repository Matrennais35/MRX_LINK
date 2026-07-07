"""The Writer — assembles the desk note Answer from the loop's final markdown,
the blueprint, and the session's section-tagged artifacts.

The note's own '## headings' define the delivered structure (the model may
have amended the blueprint — contract-of-qualities rule); artifacts attach by
title. A blueprint section that was neither written nor filled becomes a
VISIBLE unfilled section with its contract as the reason — never a silent drop.
"""

import re
from typing import Dict, List, Tuple

from ..common.answer import Answer, Section

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def split_report(markdown: str) -> Tuple[str, List[Tuple[str, str]]]:
    """(executive_summary, [(title, text), ...]) — text before the first
    '## ' heading is the summary; unparseable output degrades to whole-text-
    as-summary (a formatting slip must never lose an answer)."""
    parts = _HEADING_RE.split(markdown)
    summary = parts[0].strip()
    sections = [(parts[i].strip(), parts[i + 1].strip())
                for i in range(1, len(parts) - 1, 2)]
    return (summary or markdown.strip()), sections


def assemble(markdown: str, blueprint, session) -> Answer:
    """Build the Answer: the note's delivered sections (artifacts attached by
    title), plus visible gaps for undelivered blueprint contracts."""
    summary, texted = split_report(markdown)
    sections: List[Section] = []
    delivered = set()

    for title, text in texted:
        artifacts = session.artifacts_for(title)
        chart = next((a.obj for a in artifacts if a.kind == "chart"), None)
        table_artifact = next((a for a in artifacts if a.kind == "table"), None)
        sections.append(Section(
            title=title, text=text, chart=chart,
            table=table_artifact.obj if table_artifact else None,
            full_table=bool(table_artifact and table_artifact.full),
        ))
        delivered.add(title.strip().casefold())

    # Undelivered blueprint contracts surface as visible gaps.
    for spec in getattr(blueprint, "sections", []):
        key = spec.title.strip().casefold()
        if key in delivered or session.artifacts_for(spec.title):
            continue
        sections.append(Section(
            title=spec.title, status="unfilled",
            reason=f"not delivered (was to establish: {spec.must_establish})",
        ))

    primary_table = next((s.table for s in sections if s.table is not None), None)
    primary_chart = next((s.chart for s in sections if s.chart is not None), None)
    return Answer(narrative=summary, sections=sections,
                  table=primary_table, chart=primary_chart)
