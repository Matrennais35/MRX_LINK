"""Chart builders — the representations an analytical answer deserves,
built deterministically from a computed table (no LLM-drawn matplotlib).

waterfall: attribution ("what drove the move" — contributions stacking to a
net); ranked_bar: signed rankings (top contributors +/-); evolution: a series
over time. All use the ported _CHART_STYLE so they match the app's theme, and
return live Figures (they pass codegen's _validated_figure by construction).
"""

from typing import List, Optional

import matplotlib.pyplot as plt
import pandas as pd

# The shared dark-theme chart style (moved from the retired codegen module).
_CHART_STYLE = {
    "figure.facecolor": "#141619",
    "axes.facecolor": "#141619",
    "axes.edgecolor": "#2A2E33",
    "axes.labelcolor": "#C9CDD3",
    "text.color": "#C9CDD3",
    "xtick.color": "#6B7280",
    "ytick.color": "#6B7280",
    "grid.color": "#2A2E33",
    "axes.prop_cycle": plt.cycler(color=["#E8A33D", "#6B7280", "#C9CDD3"]),
    "font.family": "monospace",
}

_POS = "#2E7D32"   # green for positive contributions
_NEG = "#C62828"   # red for negative
_NET = "#E8A33D"   # accent for the net bar


def waterfall(labels: List[str], values: List[float], title: str = "") -> plt.Figure:
    """Contribution waterfall: each bar starts where the previous ended,
    closing with a NET bar — the canonical attribution picture."""
    with plt.rc_context(_CHART_STYLE):
        fig, ax = plt.subplots(figsize=(8, 4))
        running = 0.0
        for i, (label, value) in enumerate(zip(labels, values)):
            ax.bar(i, value, bottom=running, color=_POS if value >= 0 else _NEG)
            running += value
        ax.bar(len(labels), running, color=_NET)
        ax.set_xticks(range(len(labels) + 1))
        ax.set_xticklabels(list(labels) + ["NET"], rotation=30, ha="right", fontsize=8)
        ax.axhline(0, linewidth=0.8)
        if title:
            ax.set_title(title)
        fig.tight_layout()
    return fig


def ranked_bar(labels: List[str], values: List[float], title: str = "") -> plt.Figure:
    """Horizontal signed ranking — largest |value| at the top, color by sign."""
    with plt.rc_context(_CHART_STYLE):
        fig, ax = plt.subplots(figsize=(8, max(2.5, 0.35 * len(labels))))
        order = list(range(len(labels)))[::-1]  # largest on top
        ax.barh([order[i] for i in range(len(labels))], values,
                color=[_POS if v >= 0 else _NEG for v in values])
        ax.set_yticks(order)
        ax.set_yticklabels(labels, fontsize=8)
        ax.axvline(0, linewidth=0.8)
        if title:
            ax.set_title(title)
        fig.tight_layout()
    return fig


def evolution(x: List, y: List[float], title: str = "", ylabel: str = "") -> plt.Figure:
    """A series over time (dates on x)."""
    with plt.rc_context(_CHART_STYLE):
        fig, ax = plt.subplots(figsize=(8, 3.6))
        ax.plot(x, y, marker="o", markersize=3)
        if len(x) > 10:
            step = max(1, len(x) // 10)
            ax.set_xticks(list(x)[::step])
        ax.tick_params(axis="x", rotation=30, labelsize=8)
        if ylabel:
            ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)
        fig.tight_layout()
    return fig
