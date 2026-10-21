# OMR Data Collector

A desktop app (macOS, Windows, Linux) for service providers who collect data on paper:

1. **Build** printable forms from reusable blocks: text, questions and tables of
   bubble or hand-written fields, with a QR code naming the organization and form.
2. **Capture** photos or scans of the filled-in forms, read the bubbles with
   [OMRChecker](https://github.com/Udayraj123/OMRChecker), and let staff check the
   result against the image and key in hand-written fields.
3. **Export** the data as CSV or JSON.

## Installing

Installers for Windows, macOS (Apple Silicon and Intel) and Linux go on the
[Releases](https://github.com/mstewart14/omr-data-collector/releases) page. They
aren't signed, so the first run needs one extra step:
[packaging/README.md](packaging/README.md#unsigned-for-now) says what to do for Windows or Mac.

## Getting started

Needs [uv](https://docs.astral.sh/uv/) to build on your local system. 

to install uv

on macOS and Linux (in Terminal):
```curl -LsSf https://astral.sh/uv/install.sh | sh
```

on Windows (in PowerShell):
```powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

On Linux under X11, Qt also needs `libxcb-cursor0` to open windows
(`apt install libxcb-cursor0`); without it the app exits with "Could not load the Qt
platform plugin xcb".

On all platforms in a terminal (powershell on windows)
```
uv sync
uv run pre-commit install --install-hooks
uv run omr-data-collector     # or: uv run python -m omr_data_collector
```

## Accessibility

The app aims for [WCAG 2.2](https://www.w3.org/TR/WCAG22/) level AA as it applies to
desktop software, since the people entering data may use screen readers, only a
keyboard, or large fonts and high-contrast themes:

- every field is labelled for screen readers and has an Alt+letter shortcut; Ctrl+S
  saves
- errors are written out (not shown by color alone), read out when their field gets
  focus, and focus moves to the first one when saving fails
- status messages such as "Organization saved." are announced to screen readers
- error colors keep at least 4.5:1 contrast on light, dark and high-contrast themes
- layouts follow the system font size

`omr_data_collector/ui/accessibility.py` holds the shared helpers and
`tests/test_accessibility.py` checks each point. On Linux, screen readers such as Orca
reach the app through AT-SPI; Qt's `qt.accessibility.atspi` log lines are its
bridge talking to that service, not errors.

## Translations

All the app's text can be translated, with Qt's translation tools. English is the
source language; the catalogs live in `omr_data_collector/translations/`.

- **Starting a language:** `uv run python scripts/update_translations.py --add fr`
  creates `omr_data_collector_fr.ts`. Translate it with Qt Linguist
  (`uv run pyside6-linguist`) or any tool that reads .ts files, such as Weblate.
- **After changing any text:** run `uv run python scripts/update_translations.py`
  and commit the updated .ts and .qm files. It collects every `tr()` string,
  keeps existing translations, fills in English's plural forms and compiles the
  .qm files the app loads. A test fails if they are out of date.
- **Choosing a language:** the app follows the desktop's language unless one is
  chosen in Preferences > Language (kept per person, with QSettings, and used from
  the next start). A language without a translation shows in English. Each
  catalog names its own language: translate "English" (noted "the name of this
  language, in this language") as, say, "Français".
- **Trying a language:** `OMR_DATA_COLLECTOR_LANGUAGE=fr uv run omr-data-collector`
  overrides both, and
  `OMR_DATA_COLLECTOR_LANGUAGE=pseudo` shows every translatable string accented and
  about a third longer, to spot untranslated text and layouts that can't stretch.

Writing translatable text (see `omr_data_collector/i18n.py`):

- wrap it in `tr()` as one literal sentence; put values in afterwards with named
  placeholders: `tr('Saved "{name}".').format(name=name)`. Never build sentences
  from pieces or f-strings: word order, gender and case differ between languages
- counts use plural forms, passed by position: `tr("%n page(s)", None, pages)`
- text in module-level constants is translated too early; keep it in functions
- words printed on the forms use `tr_printed()`, kept apart from the app's own text
- each language's labels need their own Alt+letter shortcuts, unique on each page
  and clear of the menu bar's; the mnemonic tests run in every language

`tests/test_translations.py` checks that every page, menu and dialog is
translatable (under the pseudo-translation), that no prose is left outside `tr()`,
and that translations keep their placeholders.

## Development

Code follows PEP 8 and the conventions of OMRChecker v2, using the same tooling:

- **uv** for the environment and lockfile
- **ruff** for linting (`select = ["ALL"]` with OMRChecker's ignore list) and formatting
  (Black-compatible, 88 columns); `ruff.toml` is copied from OMRChecker
- **pyright** in basic mode
- **pre-commit** runs all of the above; a quick test on commit, the full suite with
  coverage on push
- File names: PascalCase for a module holding one class named after it
  (`MainWindow.py`), snake_case otherwise (`runner.py`)
- [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/#summary)

Two deliberate exceptions: methods overriding Qt's own keep Qt's camelCase names
(`paintEvent`), and the project targets current Python rather than upstream's minimum.

```bash
uv run pytest                 # all tests
uv run ruff check --fix && uv run ruff format
uv run pyright
```


## Icon and packaging files

The app icon is `omr_data_collector/resources/app-icon.svg`, with
`app-icon-small.svg` drawn simpler for 16-24 px. `uv run python
scripts/build_icons.py` builds `packaging/icons/` from them: PNGs at the usual
sizes, a multi-size Windows `.ico` and macOS `.icns`. On Linux,
`packaging/linux/omr-data-collector.desktop` is the menu entry; install it with
the PNGs (as `omr-data-collector.png` in the hicolor theme) so desktops show the
icon in the task bar; the AppImage does.

The installers, how they're built and how to make a release are in
[packaging/README.md](packaging/README.md).

## The vendored OMR engine

`vendor/omrchecker/` is OMRChecker v2 (its `dev` branch), added as a squashed git
subtree pinned to a specific upstream commit. **Don't edit it here**; work around engine
issues in `omr_data_collector/engine/` instead. To move to a newer upstream commit:

```bash
git subtree pull --prefix=vendor/omrchecker --squash \
    https://github.com/Udayraj123/OMRChecker.git <commit-or-branch>
```

OMRChecker's top-level package is named `src`, so it can't be installed as a normal
dependency. `omr_data_collector/engine/` puts it on the import path; only that package
imports from `src`. Its runtime dependencies are listed in our `pyproject.toml` at the
versions OMRChecker pins (see the comment there for the three deliberate differences).

## License

MIT (`LICENSE`), the same as OMRChecker. The vendored OMRChecker is © Udayraj
Deshmukh and contributors, under its own MIT license (`vendor/omrchecker/LICENSE`).
Qt for Python (PySide6) is used under the LGPL v3.
