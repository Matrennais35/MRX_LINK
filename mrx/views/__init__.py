"""View registry — the "capability as data" layer.

Adding an MRX view means adding a View implementation and registering it here;
the core (fetch / router / loop) never imports a specific view. A plain typed
Python registry rather than YAML + a loader — over-engineering for a handful
of typed views (see docs/view_interface_design.md).
"""

from .base import View
from .multirow.view import MultirowView

REGISTRY: dict[str, View] = {
    MultirowView.name: MultirowView(),
}

# The view used when a caller doesn't specify one. Today there's exactly one
# view, so this is simply it; when a second view lands, per-question view
# SELECTION gets wired (the interface already allows passing a view through) —
# this default just keeps every existing single-view call working meanwhile.
DEFAULT_VIEW: View = REGISTRY[MultirowView.name]


def get_view_impl(name: str) -> View:
    """Look up a registered view by name, or raise KeyError if unknown."""
    return REGISTRY[name]
