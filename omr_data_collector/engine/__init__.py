"""Bridge to the vendored OMRChecker v2 engine in vendor/omrchecker.

OMRChecker's top-level package is literally named ``src`` and imports itself
absolutely (``from src.utils ...``), so it can't be installed as an ordinary
dependency. Its repository root goes on ``sys.path`` instead, and only modules in
this package should import from ``src``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

OMRCHECKER_ROOT = Path(__file__).resolve().parents[2] / "vendor" / "omrchecker"

# OMRChecker looks up the monitor size when it is imported, for its OpenCV debug
# windows. The app never opens those windows (images are shown through Qt), and the
# lookup raises on machines it can't query, such as pure Wayland sessions or CI, so
# use OMRChecker's own fake-monitor switch.
os.environ.setdefault("OMR_CHECKER_CONTAINER", "1")

if str(OMRCHECKER_ROOT) not in sys.path:
    # Appended rather than prepended so the vendored repository's top-level modules
    # (main.py, conftest.py) never shadow anything else on the path.
    sys.path.append(str(OMRCHECKER_ROOT))
