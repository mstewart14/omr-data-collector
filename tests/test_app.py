from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from omr_data_collector import APP_NAME, app, engine_preload
from omr_data_collector.constants import DATABASE_FILENAME
from omr_data_collector.engine_preload import start_engine_preload
from omr_data_collector.ui import startup_splash
from omr_data_collector.ui.MainWindow import MainWindow
from omr_data_collector.ui.startup_splash import show_startup_splash, show_step

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot


def test_main_shows_main_window_and_returns_exit_code(
    qtbot: QtBot, mocker: MockerFixture, tmp_path: Path
) -> None:
    # pytest-qt already owns the process's one QApplication, so main() gets a stand-in
    # whose event loop returns at once.
    application_class = mocker.patch.object(app, "QApplication")
    application_class.return_value.exec.return_value = 3
    # The real application keeps the tests' translators.
    install_translators = mocker.patch.object(app, "install_translators")
    database_path = tmp_path / "app-data" / DATABASE_FILENAME
    mocker.patch.object(app, "default_database_path", return_value=database_path)

    windows: list[MainWindow] = []

    def create_window(connection) -> MainWindow:
        window = MainWindow(connection)
        qtbot.addWidget(window)
        windows.append(window)
        return window

    mocker.patch.object(app, "main_window_class", return_value=create_window)

    assert app.main() == 3

    application_class.return_value.setApplicationName.assert_called_once_with(APP_NAME)
    install_translators.assert_called_once_with(application_class.return_value)
    application_class.return_value.setWindowIcon.assert_called_once()
    application_class.return_value.setDesktopFileName.assert_called_once_with(
        "omr-data-collector"
    )
    assert len(windows) == 1
    assert windows[0].isVisible()
    assert database_path.exists()


def modules_loaded_by(module: str) -> str:
    code = (
        f"import sys; import {module}; "
        "print(sorted({'cv2', 'pandas', 'scipy', 'src'} & set(sys.modules)))"
    )
    result = subprocess.run(  # noqa: S603 (our own interpreter and code)
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_splash_shows_before_the_engine_loads() -> None:
    # The splash is only evidence of starting if it can be shown before the slow
    # imports, so nothing it needs may bring them in.
    assert modules_loaded_by("omr_data_collector.app") == "[]"


def test_main_window_opens_without_the_scanning_engine() -> None:
    # OMRChecker and its libraries load in the background once the window is
    # up (engine_preload); OpenCV alone, for QR codes, is quick enough.
    assert modules_loaded_by("omr_data_collector.ui.MainWindow") == "['cv2']"


def test_main_starts_loading_the_engine_once_the_window_shows(
    qtbot: QtBot, mocker: MockerFixture, tmp_path: Path
) -> None:
    application_class = mocker.patch.object(app, "QApplication")
    application_class.return_value.exec.return_value = 0
    mocker.patch.object(app, "install_translators")
    mocker.patch.object(
        app, "default_database_path", return_value=tmp_path / DATABASE_FILENAME
    )
    windows: list[MainWindow] = []

    def create_window(connection) -> MainWindow:
        window = MainWindow(connection)
        qtbot.addWidget(window)
        windows.append(window)
        return window

    mocker.patch.object(app, "main_window_class", return_value=create_window)
    window_shown_first: list[bool] = []
    mocker.patch.object(
        app,
        "preload_engine_later",
        side_effect=lambda: window_shown_first.append(windows[0].isVisible()),
    )

    app.main()

    assert window_shown_first == [True]


def test_engine_preload_imports_the_module_on_a_thread() -> None:
    # A module the tests haven't loaded, so the import really happens here.
    name = "omr_data_collector.export.data_export"
    sys.modules.pop(name, None)

    thread = start_engine_preload(name)
    thread.join(timeout=60)

    assert thread.daemon
    assert name in sys.modules


def test_engine_preload_leaves_a_failure_to_the_screen_that_needs_it() -> None:
    thread = start_engine_preload("omr_data_collector.no_such_module")
    thread.join(timeout=10)

    assert not thread.is_alive()


def test_engine_preload_waits_for_the_event_loop(
    qtbot: QtBot, mocker: MockerFixture
) -> None:
    start = mocker.patch.object(engine_preload, "start_engine_preload")

    engine_preload.preload_engine_later(delay_ms=10)

    start.assert_not_called()
    qtbot.waitUntil(lambda: start.call_count == 1)


def test_splash_names_itself_and_says_what_is_happening(qtbot: QtBot) -> None:
    splash = show_startup_splash()
    qtbot.addWidget(splash)

    show_step(splash, "Opening your forms…")

    assert splash.isVisible()
    assert APP_NAME in splash.accessibleName()
    assert splash.accessibleDescription()
    assert splash.message() == "Opening your forms…"
    assert not splash.pixmap().isNull()


def test_splash_shows_the_version_and_the_code_link(mocker: MockerFixture) -> None:
    mocker.patch.object(startup_splash, "app_version", return_value="1.2.3")

    details = startup_splash.splash_details()

    assert details == ["Version 1.2.3", "github.com/mstewart14/omr-data-collector"]


def test_splash_without_a_recorded_version_says_so(mocker: MockerFixture) -> None:
    mocker.patch.object(startup_splash, "app_version", return_value="")

    assert startup_splash.splash_details()[0] == "Version unknown"
