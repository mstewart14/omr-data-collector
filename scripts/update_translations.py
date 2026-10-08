# ruff: noqa: INP001 (a standalone tool, not part of a package)
"""Collect the app's translatable text into the .ts catalogs, and compile them.

usage: uv run python scripts/update_translations.py [--add LANGUAGE ...]

- Runs pyside6-lupdate over the app's source into every
  ``omr_data_collector/translations/omr_data_collector_<language>.ts``, keeping
  what translators have done and dropping strings no longer used.
- ``--add fr`` (or fr_CA, de...) starts a catalog for a new language.
- English is the source language, so its catalog holds only the strings with a
  count (``%n``), whose singular and plural English forms are filled in here
  from the "(s)" in the source: "%n page(s)" becomes "%n page" and "%n pages".
- Compiles each catalog into the .qm file the app loads, with pyside6-lrelease.

Run it after changing any text, and commit the .ts and .qm files: a test fails
when they are out of date.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "omr_data_collector"
TRANSLATIONS = PACKAGE / "translations"
CATALOG_NAME = "omr_data_collector"
SOURCE_LANGUAGE = "en"


def catalog_path(language: str, directory: Path = TRANSLATIONS) -> Path:
    return directory / f"{CATALOG_NAME}_{language}.ts"


def source_files() -> list[Path]:
    return sorted(
        path for path in PACKAGE.rglob("*.py") if "__pycache__" not in path.parts
    )


def update(directory: Path = TRANSLATIONS, add: tuple[str, ...] = ()) -> list[Path]:
    """Update (or create) every catalog in ``directory``; returns them."""
    directory.mkdir(parents=True, exist_ok=True)
    languages = {SOURCE_LANGUAGE, *add}
    languages |= {
        path.stem.removeprefix(f"{CATALOG_NAME}_")
        for path in directory.glob(f"{CATALOG_NAME}_*.ts")
    }
    catalogs = []
    for language in sorted(languages):
        catalog = catalog_path(language, directory)
        command = [
            "pyside6-lupdate",
            *map(str, source_files()),
            "-no-obsolete",
            # Line numbers would change the catalogs with every edit.
            "-locations",
            "none",
            "-source-language",
            SOURCE_LANGUAGE,
            "-target-language",
            language,
            "-ts",
            str(catalog),
        ]
        if language == SOURCE_LANGUAGE:
            command.insert(1, "-pluralonly")
        run(command)
        if language == SOURCE_LANGUAGE:
            fill_english_plurals(catalog)
        catalogs.append(catalog)
    return catalogs


def fill_english_plurals(catalog: Path) -> None:
    """Give every "(s)" message its English singular and plural."""
    tree = ET.parse(catalog)  # noqa: S314 (our own catalog, just written by lupdate)
    for message in tree.iter("message"):
        source = message.findtext("source", "")
        translation = message.find("translation")
        if translation is None:
            continue
        singular = re.sub(r"\(s\)", "", source)
        plural = re.sub(r"\(s\)", "s", source)
        for form in list(translation):
            translation.remove(form)
        for text in (singular, plural):
            ET.SubElement(translation, "numerusform").text = text
        translation.attrib.pop("type", None)
    ET.indent(tree, space="    ")
    tree.write(catalog, encoding="utf-8", xml_declaration=True)
    with catalog.open("a", encoding="utf-8") as file:
        file.write("\n")


def compile_catalogs(catalogs: list[Path]) -> None:
    for catalog in catalogs:
        run(
            [
                "pyside6-lrelease",
                "-silent",
                str(catalog),
                "-qm",
                str(catalog.with_suffix(".qm")),
            ]
        )


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603 (our own tool's commands)
    # lupdate reports strings it can't read (an f-string passed to tr, say) as
    # warnings but still succeeds; they must be fixed, so they fail here.
    output = result.stdout + result.stderr
    problems = [
        line
        for line in output.splitlines()
        if "warning" in line.lower() or "error" in line.lower()
    ]
    if result.returncode or problems:
        sys.stderr.write(output)
        msg = f"{command[0]} failed"
        raise SystemExit(msg)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--add", action="append", default=[], metavar="LANGUAGE")
    arguments = parser.parse_args()
    compile_catalogs(update(add=tuple(arguments.add)))


if __name__ == "__main__":
    main()
