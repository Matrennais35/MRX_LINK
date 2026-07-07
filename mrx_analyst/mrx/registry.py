"""The view registry — the only place that names concrete MRX views.

MRX_SIM=1 in the environment swaps the default view for the SIMULATOR
(mrx/sim.py): same real validation gate, same URL parameters, same frame
shapes — synthetic data with planted ground-truth stories. The entire
framework (app, harnesses, evals) runs unchanged and offline.
"""

import os

from .base import View
from .view import MultirowView

REGISTRY = {MultirowView.name: MultirowView()}

if os.getenv("MRX_SIM"):
    from .sim import SimMRXView
    REGISTRY[SimMRXView.name] = SimMRXView()
    DEFAULT_VIEW = REGISTRY[SimMRXView.name]
    print("*** MRX_SIM active: the SIMULATOR serves all fetches "
          "(synthetic data, real validation) ***")
else:
    DEFAULT_VIEW = REGISTRY[MultirowView.name]
