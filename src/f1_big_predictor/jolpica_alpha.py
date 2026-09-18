from __future__ import annotations

import sys

from .data import jolpica_alpha as _jolpica_alpha
from .data.jolpica_alpha import *

sys.modules[__name__] = _jolpica_alpha
