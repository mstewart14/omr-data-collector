"""Loading the scanning engine in the background once the window is up.

Reading sheets needs OMRChecker, and with it pandas, SciPy and matplotlib:
seconds to load, far longer on a first launch while the system scans every
library. Nothing imports it while the app starts, so the window opens first;
then it loads on a thread, so the first sheet read rarely waits. A screen that
needs it before then imports it as usual and waits for the loading to finish
(Python lets only one thread import a module at a time).

The thread shares Python with the window, so the window answers a little more
slowly while it runs, but it never stops answering.
"""

from __future__ import annotations

import importlib
import threading

from PySide6.QtCore import QTimer

ENGINE_MODULE = "omr_data_collector.engine.reading"
# Long enough for the window to finish drawing before the loading competes with it.
PRELOAD_DELAY_MS = 1000


def preload_engine_later(delay_ms: int = PRELOAD_DELAY_MS) -> None:
    """Start loading the engine on a thread once the event loop has run a while."""
    QTimer.singleShot(delay_ms, start_engine_preload)


def start_engine_preload(module: str = ENGINE_MODULE) -> threading.Thread:
    # A daemon, so closing the app soon after it opens never waits for the loading.
    thread = threading.Thread(
        target=_load, args=(module,), name="engine-preload", daemon=True
    )
    thread.start()
    return thread


def _load(module: str) -> None:
    try:
        importlib.import_module(module)
    except Exception:
        # Nothing to report here: the screen that needs the engine imports it
        # again, and that is where a failure shows, with its reason.
        return
