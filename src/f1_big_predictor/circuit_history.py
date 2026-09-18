from __future__ import annotations

import sys

from .data import circuit_history as _circuit_history
from .data.circuit_history import *

sys.modules[__name__] = _circuit_history
