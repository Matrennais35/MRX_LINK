"""The view registry — the only place that names concrete MRX views."""

from .base import View
from .view import MultirowView

REGISTRY = {MultirowView.name: MultirowView()}
DEFAULT_VIEW = REGISTRY[MultirowView.name]
