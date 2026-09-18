from __future__ import annotations

import sys

from .data import archive as _archive
from .data.archive import *

sys.modules[__name__] = _archive
