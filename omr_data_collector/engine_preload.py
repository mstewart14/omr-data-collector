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
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

if TYPE_CHECKING:
    from collections.abc import Callable

ENGINE_MODULE = "omr_data_collector.engine.reading"
# Long enough for the window to finish drawing before the loading competes with it.
PRELOAD_DELAY_MS = 1000


def preload_engine_later(
    delay_ms: int = PRELOAD_DELAY_MS, *, on_done: Callable[[], None] | None = None
) -> None:
    """Start loading the engine on a thread once the event loop has run a while.

    ``on_done`` is called on that thread once the loading ends, however it ends.
    """
    QTimer.singleShot(delay_ms, lambda: start_engine_preload(on_done=on_done))


def start_engine_preload(
    module: str = ENGINE_MODULE, *, on_done: Callable[[], None] | None = None
) -> threading.Thread:
    # A daemon, so closing the app soon after it opens never waits for the loading.
    thread = threading.Thread(
        target=_load, args=(module, on_done), name="engine-preload", daemon=True
    )
    thread.start()
    return thread


def _load(module: str, on_done: Callable[[], None] | None) -> None:
    try:
        importlib.import_module(module)
    except Exception:  # noqa: S110 (nothing to report here)
        # The screen that needs the engine imports it again, and that is where
        # a failure shows, with its reason.
        pass
    finally:
        if on_done is not None:
            on_done()
