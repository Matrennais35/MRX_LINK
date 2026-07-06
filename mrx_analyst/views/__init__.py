"""MRX view plug-ins. A View owns plan/validate/execute/fingerprint for one
MRX report type; the registry is the only place that names concrete views.
"""

from .base import View
from .multirow.view import MultirowView

REGISTRY = {MultirowView.name: MultirowView()}
DEFAULT_VIEW = REGISTRY[MultirowView.name]
