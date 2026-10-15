"""Every string people see can be translated, and the catalogs are up to date."""

from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTableWidget,
    QTextEdit,
    QWidget,
)

from omr_data_collector.constants import BLOCK_KINDS
from omr_data_collector.export.data_export import ExportNames, OutputFile
from omr_data_collector.i18n import (
    TRANSLATIONS_DIR,
    PseudoTranslator,
    install_translators,
    language_choices,
    pseudo_translate,
    tr,
)
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.ui.BlockDialogs import BlockContentDialog, BlockPickerDialog
from omr_data_collector.ui.ColumnDialog import ColumnDialog
from omr_data_collector.ui.ExportDialog import ExportDialog
from omr_data_collector.ui.ExportNamesDialog import ExportNamesDialog
from omr_data_collector.ui.LanguageDialog import LanguageDialog
from omr_data_collector.ui.MainWindow import MainWindow
from omr_data_collector.ui.OpenFormDialog import OpenFormDialog
from omr_data_collector.ui.SheetDetailsDialog import SheetDetailsDialog

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> Any:  # noqa: ANN401 (a module)
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


update_translations = _load_script("update_translations")

PLACEHOLDER = re.compile(r"\{[^}]*\}|%n")
# Names, the same in every language.
PROPER_NAMES = {"Damm", "Verhoeff", "OMR Data Collector"}


@pytest.fixture
def pseudo(qapp: QApplication) -> Iterator[None]:
    """Show every translatable string pseudo-translated, as in ⟦Šåvé~~⟧."""
    translator = PseudoTranslator()
    qapp.installTranslator(translator)
    yield
    qapp.removeTranslator(translator)
    install_translators(qapp, QLocale(QLocale.Language.English))


def shown_texts(root: QWidget) -> list[tuple[str, str]]:
    """Every piece of text ``root`` shows or tells screen readers, by where it is.

    Leaves out what people type (line and text edits' contents).
    """
    return [
        (where, text)
        for widget in [root, *root.findChildren(QWidget)]
        for where, text in _widget_texts(widget)
        if text.strip()
    ]


def _widget_texts(widget: QWidget) -> list[tuple[str, str]]:
    name = type(widget).__name__
    texts = [
        (f"{name} tooltip", widget.toolTip()),
        (f"{name} accessible name", widget.accessibleName()),
        (f"{name} accessible description", widget.accessibleDescription()),
    ]
    if widget.isWindow():
        texts.append((f"{name} window title", widget.windowTitle()))
    if isinstance(widget, (QLabel, QAbstractButton)) and not isinstance(
        widget.parent(), QComboBox
    ):
        texts.append((f"{name} text", widget.text()))
    if isinstance(widget, (QGroupBox, QMenu)):
        texts.append((f"{name} title", widget.title()))
    if isinstance(widget, QComboBox):
        texts += [(f"{name} item", widget.itemText(i)) for i in range(widget.count())]
    if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
        texts.append((f"{name} placeholder", widget.placeholderText()))
    if isinstance(widget, QTableWidget):
        headers = (widget.horizontalHeaderItem(i) for i in range(widget.columnCount()))
        texts += [(f"{name} header", item.text()) for item in headers if item]
    if isinstance(widget, QMenu):
        texts += [(f"{name} item", action.text()) for action in widget.actions()]
    return texts


def untranslated(root: QWidget) -> list[tuple[str, str]]:
    # Numbers, punctuation and keyboard shortcuts are the same in every language.
    return [
        (where, text)
        for where, text in shown_texts(root)
        if PseudoTranslator.START not in text
        and text not in PROPER_NAMES
        # Each language is named in itself, whatever the app is showing.
        and text not in {name for _, name in language_choices()[1:]}
        and re.search(r"[A-Za-z]{2}", text.split("\t")[0])
        and not re.fullmatch(r"(Ctrl|Shift|Alt|Meta|\+|[A-Z0-9]|\s)+", text)
    ]


@pytest.mark.usefixtures("pseudo")
def test_every_page_and_menu_is_translatable(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = MainWindow(connection)
    qtbot.addWidget(window)

    for index in range(len(window.pages)):
        window.open_section(index)
    # Pages show some controls only for some choices; show them all.
    for page in (window.questions_page, window.tables_page):
        combo = getattr(page, "answer_fields", None)
        if combo is not None:
            for index in range(combo.answer_type_combo.count()):
                combo.answer_type_combo.setCurrentIndex(index)

    found = untranslated(window)
    for page in (window.questions_page, window.tables_page):
        page.revert()  # so closing the window doesn't ask about it
    assert found == []


@pytest.mark.usefixtures("pseudo")
@pytest.mark.parametrize(
    "make_dialog",
    [
        lambda: ColumnDialog(None, None, set()),
        lambda: BlockContentDialog(None, BLOCK_KINDS.TEXT, None),
        lambda: BlockContentDialog(None, BLOCK_KINDS.QUESTION, None),
        lambda: BlockPickerDialog(None, BLOCK_KINDS.TEXT, [], can_write_new=True),
        lambda: BlockPickerDialog(None, BLOCK_KINDS.TABLE, [], can_write_new=False),
        lambda: OpenFormDialog(None, [], set()),
        lambda: LanguageDialog(None, ""),
        lambda: SheetDetailsDialog(None, SheetDetails(name="Sheet details")),
        lambda: ColumnDialog(None, None, set(), sheet_detail=True),
        lambda: ExportDialog(None, []),
        lambda: ExportNamesDialog(
            None,
            [OutputFile("sheets", ("sheet_id", "visit"))],
            ExportNames(),
        ),
    ],
    ids=[
        "column",
        "text",
        "question",
        "text picker",
        "table picker",
        "open form",
        "language",
        "sheet details",
        "sheet detail field",
        "export",
        "export names",
    ],
)
def test_every_dialog_is_translatable(qtbot: QtBot, make_dialog) -> None:
    dialog = make_dialog()
    qtbot.addWidget(dialog)

    assert untranslated(dialog) == []


def test_pseudo_translation_keeps_what_code_and_qt_rely_on() -> None:
    assert pseudo_translate('Sa&ve "{name}" in %n place(s) <b>now</b>') == (
        '⟦Šå&vé "{name}" îñ %n pĺåçé(š) <b>ñöw</b>~~~~~~~~~~~~~⟧'
    )


def test_english_counts_read_naturally() -> None:
    assert tr("%n page(s).", None, 1) == "1 page."
    assert tr("%n page(s).", None, 2) == "2 pages."


def run_lupdate(arguments: list[str]) -> None:
    update_translations.run(
        ["pyside6-lupdate", *map(str, update_translations.source_files()), *arguments]
    )


def test_every_count_is_a_plural_message(tmp_path: Path) -> None:
    """A count passed by keyword (n=) is invisible to lupdate: "(s)" would show."""
    catalog = tmp_path / "all.ts"
    run_lupdate(["-locations", "none", "-ts", str(catalog)])

    singular_only = [
        message.findtext("source")
        for message in ET.parse(catalog).iter("message")  # noqa: S314 (just written)
        if "%n" in (message.findtext("source") or "")
        and message.get("numerus") != "yes"
    ]

    assert singular_only == []


def test_catalogs_are_up_to_date(tmp_path: Path) -> None:
    """Fails when text changed without running scripts/update_translations.py."""
    for catalog in TRANSLATIONS_DIR.glob("*.ts"):
        shutil.copy(catalog, tmp_path)

    update_translations.update(tmp_path)

    for catalog in TRANSLATIONS_DIR.glob("*.ts"):
        assert (tmp_path / catalog.name).read_text() == catalog.read_text(), (
            f"{catalog.name} is out of date: run "
            "uv run python scripts/update_translations.py"
        )
    update_translations.compile_catalogs(sorted(tmp_path.glob("*.ts")))
    for catalog in TRANSLATIONS_DIR.glob("*.ts"):
        compiled = catalog.with_suffix(".qm")
        assert compiled.exists(), f"{compiled.name} is missing"
        assert (tmp_path / compiled.name).read_bytes() == compiled.read_bytes(), (
            f"{compiled.name} wasn't compiled from {catalog.name}"
        )


@pytest.mark.parametrize("catalog", sorted(TRANSLATIONS_DIR.glob("*.ts")), ids=str)
def test_translations_keep_every_placeholder(catalog: Path) -> None:
    """A translation missing {name} or %n would show the wrong thing, or fail."""
    problems = []
    for message in ET.parse(catalog).iter("message"):  # noqa: S314 (our own file)
        source = message.findtext("source") or ""
        translation = message.find("translation")
        if translation is None or translation.get("type") in {"unfinished", "vanished"}:
            continue
        forms = [form.text or "" for form in translation.iter("numerusform")] or [
            translation.text or ""
        ]
        expected = sorted(PLACEHOLDER.findall(source))
        problems += [
            (source, form)
            for form in forms
            if form and sorted(PLACEHOLDER.findall(form)) != expected
        ]

    assert problems == []


def test_lupdate_is_available() -> None:
    assert (
        shutil.which("pyside6-lupdate")
        or subprocess.run(
            ["pyside6-lupdate", "-version"],  # noqa: S607
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


# --- Source check: prose outside tr() -----------------------------------------------

PACKAGE = ROOT / "omr_data_collector"
TRANSLATING_CALLS = {"tr", "tr_printed", "translate"}
# Calls whose string arguments are never shown to people.
INTERNAL_CALLS = {
    "execute",
    "executescript",
    "compile",
    "QKeySequence",
    "add_shortcut",
    "getattr",
    "setObjectName",
    "setStyleSheet",
    # Log lines (not "warning", which QMessageBox shares).
    "info",
    "debug",
}
# Prose-looking strings that aren't for people to read, by file.
NOT_FOR_PEOPLE = {
    "__init__.py": {"OMR Data Collector"},
    "rendering/print_form.py": {"OMR Data Collector"},
    # Named after their inventors.
    "ui/AnswerFields.py": {"Damm", "Verhoeff"},
    # The installer builds' check: its report and its throwaway sheet.
    "self_check.py": {
        "Self check",
        "version {} read {} from form {}",
        "the app's version isn't recorded",
        "read {} where {} was marked",
        "the form's first block isn't a question",
    },
    # Exception details for logs; the scanner shows its own message instead.
    "engine/marks.py": {"{} of {} bubbles unclear"},
    "engine/runner.py": {"page or markers not found"},
    # Why a straightened page was set aside, for the log.
    "engine/alignment.py": {
        "code not found on the straightened page",
        "code {} mm from where the form puts it",
        "code turned {} degrees",
        "code {} times its printed size",
    },
}
PROSE = re.compile(r"[A-Za-z]{2,}[,.:;?!]? [A-Za-z]{2,}|^[A-Z][a-z]+$")
# SQL statements, and lists of column names.
SQL = re.compile(
    r"\s*(SELECT|INSERT|UPDATE|CREATE|DELETE|ALTER|PRAGMA)\b|[a-z_]+(, *[a-z_]+)+$"
)


def _ignored_nodes(tree: ast.AST) -> set[int]:
    """Strings that are never shown: docstrings, keys, comparisons, internals."""
    ignored: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
        ):
            ignored.add(id(body[0].value))
        inside: list[ast.AST] = []
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in TRANSLATING_CALLS | INTERNAL_CALLS:
                inside = list(node.args)
        elif isinstance(node, (ast.Subscript, ast.Compare)):
            inside = [node]
        elif isinstance(node, ast.Dict):
            inside = [key for key in node.keys if key is not None]
        elif isinstance(node, ast.JoinedStr):
            inside = list(node.values)
        ignored.update(id(sub) for part in inside for sub in ast.walk(part))
    return ignored


def _string_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            str(part.value) if isinstance(part, ast.Constant) else "{}"
            for part in node.values
        )
    return None


def _prose_outside_tr(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ignored = _ignored_nodes(tree)
    allowed = NOT_FOR_PEOPLE.get(path.relative_to(PACKAGE).as_posix(), set())
    found = []
    for node in ast.walk(tree):
        text = None if id(node) in ignored else _string_text(node)
        if (
            text is not None
            and text not in allowed
            and PROSE.search(text)
            and not SQL.match(text)
        ):
            found.append((getattr(node, "lineno", 0), text))
    return found


SOURCE_FILES = sorted(
    path
    for path in PACKAGE.rglob("*.py")
    if "schemas" not in path.parts and path.name not in {"i18n.py", "constants.py"}
)


@pytest.mark.parametrize(
    "path", SOURCE_FILES, ids=lambda path: path.relative_to(PACKAGE).as_posix()
)
def test_no_prose_outside_tr(path: Path) -> None:
    """Text for people goes through tr(); f-strings can't be translated."""
    assert _prose_outside_tr(path) == []
