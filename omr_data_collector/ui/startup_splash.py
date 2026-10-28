"""The window shown while the app starts, so starting is never silent.

Loading the rest of the app (OpenCV, OMRChecker and what they bring) takes
seconds, and far longer on a first launch, when the system scans every library
it loads. This module imports only Qt and the icon, so it can be on screen
before any of that begins.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QSplashScreen

from omr_data_collector import APP_NAME
from omr_data_collector.i18n import tr
from omr_data_collector.ui.app_icon import app_icon

# Sizes in multiples of the font's height, so the window grows with large text.
ICON_LINES = 4
MARGIN_LINES = 1.5
WIDTH_LINES = 18


def starting_message() -> str:
    return tr("Starting {app}…").format(app=APP_NAME)


def show_startup_splash() -> QSplashScreen:
    """Show the splash window at once and return it, to be closed with finish().

    Its message line (showMessage) can say what's loading now.
    """
    splash = QSplashScreen(_splash_picture())
    splash.setAccessibleName(starting_message())
    splash.setAccessibleDescription(tr("The app's window opens when it's ready."))
    splash.show()
    show_step(splash, starting_message())
    return splash


def show_step(splash: QSplashScreen, message: str) -> None:
    """Show what's happening now, drawn before the next slow step starts."""
    palette = splash.palette()
    splash.showMessage(
        message,
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
        palette.windowText().color(),
    )
    # Nothing else runs the event loop until the main window opens.
    QGuiApplication.processEvents()


def _splash_picture() -> QPixmap:
    """The icon and the app's name on the desktop's window colors.

    The message line goes in the room left below the name.
    """
    palette = QGuiApplication.palette()
    title_font = QFont(QGuiApplication.font())
    title_font.setPointSizeF(title_font.pointSizeF() * 1.5)
    title_font.setBold(True)
    line = QFontMetricsF(QGuiApplication.font()).height()
    title_height = QFontMetricsF(title_font).height()
    margin = line * MARGIN_LINES
    icon_size = round(line * ICON_LINES)
    width = round(
        max(
            line * WIDTH_LINES,
            QFontMetricsF(title_font).horizontalAdvance(APP_NAME) + 2 * margin,
        )
    )
    height = round(margin + icon_size + line + title_height + line * 2 + margin)

    # Drawn in logical units on a pixmap of physical pixels, so it's sharp on
    # Retina and other high-density screens.
    ratio = QGuiApplication.primaryScreen().devicePixelRatio()
    picture = QPixmap(round(width * ratio), round(height * ratio))
    picture.setDevicePixelRatio(ratio)
    picture.fill(palette.window().color())
    painter = QPainter(picture)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(
        QPointF((width - icon_size) / 2, margin),
        app_icon().pixmap(icon_size, icon_size),
    )
    painter.setFont(title_font)
    painter.setPen(palette.windowText().color())
    painter.drawText(
        QRectF(0, margin + icon_size + line, width, title_height),
        Qt.AlignmentFlag.AlignCenter,
        APP_NAME,
    )
    painter.setPen(palette.mid().color())
    painter.drawRect(QRectF(0, 0, width - 1, height - 1))
    painter.end()
    return picture
