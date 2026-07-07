"""The knowledge loader — the one mechanism behind "edit markdown, never code".

Knowledge files live in knowledge/ at the repo root in skill-file format:
frontmatter (name, when_to_use, examples — INDEX lines, per VISION.md) + the
markdown content. Every LLM-facing prompt is assembled from these files, so
improving intent-reading, the capability menu, or the gold standard never
touches Python.

Loaded fresh per call (no lru_cache): a knowledge edit takes effect on the
next question without restarting the app — that IS the product loop.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"

# name -> path relative to KNOWLEDGE_DIR
FILES = {
    "intent": "1_intent.md",
    "mrx_menu": "2_mrx/menu.md",
    "mrx_reading": "2_mrx/reading.md",
    "answer_standard": "3_answer_standard.md",
    "desk_context": "desk.md",
}

# The assembled prompt must stay a PROMPT, not a book — enforced by a test.
# ~4 chars/token; 40k chars ≈ 10k tokens for the whole knowledge layer.
PROMPT_CHAR_BUDGET = 40_000


@dataclass
class KnowledgeFile:
    name: str
    when_to_use: str
    content: str          # markdown body, frontmatter stripped


def _split_frontmatter(text: str):
    """Return (frontmatter_lines, body). Tolerant: no frontmatter -> ([], text)."""
    if not text.startswith("---"):
        return [], text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return [], text
    return parts[1].strip().splitlines(), parts[2].lstrip("\n")


def load(name: str) -> KnowledgeFile:
    path = KNOWLEDGE_DIR / FILES[name]
    front, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    when = ""
    for line in front:
        if line.strip().startswith("when_to_use:"):
            when = line.split(":", 1)[1].strip()
    return KnowledgeFile(name=name, when_to_use=when, content=body.strip())


def assemble(names: List[str]) -> str:
    """The given knowledge files concatenated for a prompt, in order."""
    return "\n\n".join(load(n).content for n in names)


def index() -> List[str]:
    """One line per knowledge unit — the always-visible index (the progressive-
    disclosure hook recorded in VISION.md; unused while everything fits)."""
    return [f"- {n}: {load(n).when_to_use}" for n in FILES]
