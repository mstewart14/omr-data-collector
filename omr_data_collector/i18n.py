"""Translation of the app's text, with Qt's translation system.

Every string a person sees goes through ``tr`` (or ``tr_printed`` for words
printed on the forms). ``pyside6-lupdate`` finds those calls and collects their
strings into ``translations/omr_data_collector_<language>.ts`` for translators
(Qt Linguist, or any tool that reads .ts files); ``tools/update_translations.py``
runs it and compiles the .qm files the app loads.

Rules that keep text translatable (the README's Translations section has more):

- Pass ``tr`` a whole sentence as a literal, never an f-string or pieces joined
  together: word order differs between languages. Put values in with named
  placeholders, after translating: ``tr('Saved "{name}"').format(name=name)``.
- Counts use Qt's plural forms: ``tr("%n page(s)", None, pages)``; each language
  says how many forms it has, and English's are filled in from the "(s)". The
  count must be passed by position: pyside6-lupdate doesn't see a keyword one.
- Text in module-level constants must be translated when it is used, not when
  the module is imported (before the language is chosen): keep such constants
  in functions.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

TRANSLATIONS_DIR = Path(__file__).parent / "translations"
CATALOG_NAME = "omr_data_collector"
SOURCE_LANGUAGE = "en"
# Words printed on the paper forms, kept apart from the app's own text: a form may
# one day be printed in a language other than the app's.
PRINTED_CONTEXT = "PrintedForm"
# Chooses the language instead of the system's, e.g. "fr" or "fr_CA"; "pseudo"
# shows every translatable string accented and lengthened (see PseudoTranslator).
LANGUAGE_VARIABLE = "OMR_DATA_COLLECTOR_LANGUAGE"
PSEUDO_LANGUAGE = "pseudo"

# The translators must outlive the call that installs them.
_installed: list[QTranslator] = []


def tr(text: str, disambiguation: str | None = None, n: int = -1, /) -> str:
    """The app's text in the person's language.

    Args:
        text: The English text, as a literal (``pyside6-lupdate`` reads it from
            the source).
        disambiguation: A note telling translators apart two identical English
            strings that need different translations ("Open" a file, "Open" as
            in not closed).
        n: For a count: ``%n`` in the text is replaced by it, and the language's
            plural form for it is chosen.
    """
    return QCoreApplication.translate("", text, disambiguation, n)


def tr_printed(text: str, disambiguation: str | None = None, n: int = -1, /) -> str:
    """Words printed on the forms themselves, like "continued" or page numbers."""
    return QCoreApplication.translate(PRINTED_CONTEXT, text, disambiguation, n)


def available_languages() -> list[str]:
    """The languages the app has been translated into, besides English."""
    return sorted(
        path.stem.removeprefix(f"{CATALOG_NAME}_")
        for path in TRANSLATIONS_DIR.glob(f"{CATALOG_NAME}_*.qm")
        if path.stem != f"{CATALOG_NAME}_{SOURCE_LANGUAGE}"
    )


def chosen_locale() -> QLocale:
    """The language to show: the override variable's, else the system's."""
    language = os.environ.get(LANGUAGE_VARIABLE, "")
    if language and language != PSEUDO_LANGUAGE:
        return QLocale(language)
    return QLocale.system()


def install_translators(app: QApplication, locale: QLocale | None = None) -> None:
    """Load Qt's own translations (dialog buttons and the like) and the app's.

    Missing translations aren't an error: the text stays in English.
    """
    for translator in _installed:
        app.removeTranslator(translator)
    _installed.clear()
    if os.environ.get(LANGUAGE_VARIABLE) == PSEUDO_LANGUAGE and locale is None:
        translators: list[QTranslator] = [PseudoTranslator()]
    else:
        locale = locale or chosen_locale()
        qt_translator = QTranslator()
        qt_translator.load(
            locale,
            "qtbase",
            "_",
            QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
        )
        # English first: it gives the plural forms of English text, so a
        # language with no catalog (or an unfinished one) still reads well.
        # Translators installed later are asked first.
        english = QTranslator()
        english.load(f"{CATALOG_NAME}_{SOURCE_LANGUAGE}", str(TRANSLATIONS_DIR))
        translators = [qt_translator, english]
        if locale.language() != QLocale.Language.English:
            app_translator = QTranslator()
            if app_translator.load(locale, CATALOG_NAME, "_", str(TRANSLATIONS_DIR)):
                translators.append(app_translator)
    for translator in translators:
        app.installTranslator(translator)
        _installed.append(translator)


class PseudoTranslator(QTranslator):
    """Translates everything into accented, longer English.

    Shows at a glance any text that isn't translatable (it stays plain), and any
    layout that can't take the 30-40% longer text of languages like French or
    German. Placeholders, mnemonics (&x), %n and markup are kept as they are.
    """

    START, END = "⟦", "⟧"  # ⟦ ⟧

    def isEmpty(self) -> bool:  # noqa: N802 (Qt override)
        return False

    def translate(
        self,
        context: str,  # noqa: ARG002 (all contexts alike)
        source_text: str,
        disambiguation: str | None = None,  # noqa: ARG002
        n: int = -1,  # noqa: ARG002
    ) -> str:
        return pseudo_translate(source_text)


_ACCENTED = str.maketrans(
    "AaCcEeGgIiLlNnOoSsUuYyZz",
    "ÅåÇçÉéĜĝÎîĹĺÑñÖöŠšÜüÝýŽž",
)
# Kept untouched: {placeholders}, %n and %1, mnemonics, markup tags and entities.
_KEEP = re.compile(r"\{[^}]*\}|%(?:n|L?\d)|&&|&.|<[^>]*>|&\w+;")


def pseudo_translate(text: str) -> str:
    if not text:
        return text
    pieces = []
    position = 0
    for keep in _KEEP.finditer(text):
        pieces.append(text[position : keep.start()].translate(_ACCENTED))
        pieces.append(keep.group())
        position = keep.end()
    pieces.append(text[position:].translate(_ACCENTED))
    padding = "~" * max(len(text) // 3, 1)
    return f"{PseudoTranslator.START}{''.join(pieces)}{padding}{PseudoTranslator.END}"
