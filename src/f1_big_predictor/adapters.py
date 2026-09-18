from __future__ import annotations

import sys

from .data import adapters as _adapters
from .data.adapters import *

sys.modules[__name__] = _adapters
