from __future__ import annotations

import sys

from .data import jolpica as _jolpica
from .data.jolpica import *

sys.modules[__name__] = _jolpica
