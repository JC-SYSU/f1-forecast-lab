from __future__ import annotations

import sys

from .data import actuals as _actuals
from .data.actuals import *

sys.modules[__name__] = _actuals
