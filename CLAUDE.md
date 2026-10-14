# CLAUDE.md

PySide6 desktop app: a paper form builder plus OMR capture and review, on top of a
vendored OMRChecker v2. Start with `README.md`; it covers setup, tooling and the
engine bridge.

- **Requirements** are the epics and user stories on the team wiki,
  <https://docs.stewartclan.ca/OMR%20Data%20Collector> (Otterwiki, login required).
  Read the relevant story before building a feature; the wiki is the source of truth.
- **Background research** (ID and timestamp field designs, OMR vs. manual-entry
  accuracy): "Paper-Based Data Collection: Research Summary",
  <https://claude.ai/artifact/2S9KJacwcZwoW4zJAtZuuv>.
- **Never edit `vendor/omrchecker/`.** Work around engine issues in
  `omr_data_collector/engine/`. Only that package imports from `src` (OMRChecker's
  package name).
- **Don't open issues or pull requests on OMRChecker**, or contact its maintainers,
  until the project owner says otherwise: they are first asking the OMRChecker team
  whether AI-generated contributions are welcome. Note engine bugs in our own issues.
- **One layout definition:** the form builder's blocks must generate both the printed
  PDF and the OMRChecker `template.json`, so print and scan can't drift apart. Keep a
  round-trip test (generate, render as an image, scan, compare).
- **Accessibility is a requirement, not polish.** Target WCAG 2.2 AA as it applies
  to desktop software; people using this app may rely on screen readers, the keyboard
  alone, or large fonts and high-contrast themes. Every new screen must:
  - add fields with `form_helpers.add_field_row`, which makes the `QLabel` buddy a
    sibling of its input (that sibling relation is how Qt tells screen readers the
    label; wrapping an input in a container breaks it) and adds its error row; give
    every field label and main button an Alt+letter mnemonic, unique on its page and
    never one of the menu bar's letters (`MainWindow.menu_mnemonics()`; in English F, T, Q, A, P).
    "Move up/down/left/right" buttons have none. `tests/test_menus_and_mnemonics.py`
    checks every page and dialog, so a clash fails the build;
  - say "(required)" in the label, never only in a placeholder;
  - show errors as text in a hidden-until-needed form row, set them as the
    field's accessible description, and move focus to the first invalid field:
    `accessibility.show_field_errors` does all three;
  - send status messages through the page's `status_message` signal, which
    `MainWindow.show_status` shows and announces to screen readers;
  - ask before anything that can't be undone with `form_helpers.confirm_destructive`
    (Cancel is the default) and about unsaved changes with
    `form_helpers.ask_save_discard_cancel`;
  - give images an accessible name and description;
  - set a tab order that follows the screen;
  - take colors from `accessibility` helpers checked to 4.5:1, re-chosen on
    `PaletteChange`, and size things in font units, not fixed pixels;
  - have tests for all of the above (see `tests/test_accessibility.py` and
    `tests/test_text_blocks_page.py`).
- **All text people see is translatable** (README "Translations"): wrap it in
  `i18n.tr()` as one whole literal sentence with named placeholders filled in by
  `.format()`, never an f-string or joined pieces; counts are plurals passed by
  position (`tr("%n page(s)", None, n)`); no translated text in module-level
  constants (use functions); words printed on forms use `tr_printed()`. Then run
  `uv run python scripts/update_translations.py` and commit the catalogs.
  `tests/test_translations.py` fails on text left untranslated.
- **Pages** in `MainWindow` provide `status_message`, `has_unsaved_changes()`,
  `save()` and `initial_focus`. There is no sections list: the menu bar is the
  way around (File = form editor, Text, Question, Table = libraries, Capture = captured sheets, Preferences = organization
  details and language; Ctrl+1 to Ctrl+6 for the sections), so each page gets the
  whole window. The window also handles the unsaved-changes prompt on close.
- **Block libraries** (text blocks, questions, and next tables) subclass
  `ui/LibraryPage.py`, which owns the list, New/Duplicate/Delete, the name field,
  Save/Revert and unsaved-change prompts; a subclass adds its fields in
  `build_fields` and says how to read, load, store and copy its item. How an answer
  is collected (yes/no, one or many choices, written) is an `AnswerSpec`, edited by
  `ui/AnswerFields.py`, which adds its rows to the page's own form; table columns
  reuse both.
- **Paper positions come from `layout/`:** `form_layout.layout_form` places every
  block, bubble, writing box and table row on its page, in millimetres;
  `table_layout.py` sizes table columns and cells; `text.py` measures and draws text
  against a fixed 72-dpi reference. `rendering/` draws from those layouts (the
  editor now, printing next) and the OMRChecker template must read the same
  layouts, never compute its own, so what is seen is what is printed and scanned.
- **The form editor** (`ui/FormsPage.py`) is a page view: `BlockPalette` to drag
  from, `PageCanvas` drawing the real pages (click, drag to reorder, drop to add),
  and the details panel with the Outline list. Every drag has a keyboard or menu
  equivalent (WCAG 2.2 "dragging movements"), and the canvas describes its pages
  in words; keep both true when adding features. Forms open from File > Open form.
  Every change to the form being edited must end with `_commit_change("what
  happened")`, which is what makes it undoable (Ctrl+Z) and names it in the
  "Undid: …" announcement; selection alone is not a change.
- **Forms keep their own copy of every block** (wiki 50011-50012): editing a
  library block later asks "going forward only" or "everywhere", and "everywhere"
  makes new form versions so sheets already printed still scan.
- **Printing** (`rendering/print_form.py`) draws with the same page painter as the
  editor. File > Export as PDF, Print preview and Print go through
  `FormsPage._ready_to_print` (organization entered, form saved, layout problems
  confirmed) and finish with `mark_printed`; a preview alone doesn't freeze the
  version, printing from it does.
- **Scanning:** every page has four solid corner markers in the margins
  (`layout/markers.py`), so prints are drawn full-page. `layout/omr_template.py`
  builds each page's OMRChecker template from the layout (one field per row of
  question choices, which is why choices are evenly spaced, and one per table
  cell); `TemplateField` maps each field's bubbles back to choices.
  Printing stores those templates with the version (`printed_layout`), and
  `engine/scanning.scan_sheet` reads the QR code (`qr_code.read_qr_codes`,
  OpenCV's WeChat reader: no zbar, so installers needn't bundle it), has
  OMRChecker straighten a copy of the image on the stored template and measure
  every bubble (`runner.measure_page`), and returns answers, flagging double
  marks. **OMRChecker doesn't decide what's marked:** its page-wide rule read
  every empty bubble as marked on an unevenly lit photo of light pencil.
  `engine/marks.py` judges each bubble against the paper around it, leaves
  ones in between for a person ("Couldn't tell…"), and refuses a page with
  many. Its limits are from real phone photos; retune them only against real
  photos. `tests/test_scanning.py` is the round-trip test (`Sheet.use_mark`
  and `radius_mm` draw pale and part-filled marks).
- **Sheet details** (`models/SheetDetails.py`): labelled answers (Date, Shift,
  Manager...), each field a table `Column`, written on the form (added from the form details,
  starting from a usual set) rather than kept in a library. By default
  they're stacked in the header beside the QR code on every page (one set per
  form): `layout_form` places them before stacking anything, grows the header to
  fit (`FormLayout.header_height_mm`) and narrows the names beside them; the
  other placement runs them along a line where the block is. Where they go is a
  form detail (`FormsPage.sheet_details_combo`, with Edit sheet details), not a
  setting in the sheet details dialog. Its answers are keyed `(block, None, field)` in templates and
  captures, where a question's is `(block, None, None)`.
- **Capture** (`ui/CapturePage.py`, wiki 60001-60004): images are copied into
  `captures/` beside the database (`storage/capture_store.py`, which refuses an
  image already added), read with `engine/reading.read_capture`, then checked
  answer by answer against the straightened page the scan saves. Each
  answer's place on that page comes from `PageTemplate.regions`, so the
  outline and close-up need no geometry of their own; typing goes in a
  region's `writing` area (after a question's prompt or a field's label),
  filled in by `with_writing_areas` for pages printed before it was kept. Free
  text's size is only the printed line's length, so its typed length isn't
  checked (an ID's is: one box per character). Saved data is a capture
  with status SAVED; keyed-in values are checked with `AnswerSpec.entry_error`.
  Answers are filled in on the sheet itself (`ui/SheetCanvas.py`): click and
  type over handwriting, click bubbles or press 1-9, Tab and arrows between
  answers; it draws the current values over the page, and the side list and
  editor follow it (and it them).
  `CapturedAnswer.changed_by_hand` (bubbles changed from what was read; typing
  in handwriting isn't a change) shows in the Note column and is counted in the
  export. `Capture.looks_like` warns when two pictures seem to be one sheet
  (same page, every bubble alike, no typed value different): only a warning,
  since people can mark a short form alike.
- **Export** (`export/data_export.py`, Capture > Export data): a form's saved
  captures, from every version, as a sheets CSV (sheet columns, sheet details,
  questions) plus a CSV per table (one row per filled row, repeating the sheet
  and its details), or one JSON file nesting the same. Each sheet and table row
  counts its answers changed by hand (`corrected_answers`,
  `row_corrected_answers`); the JSON names them. The columns describing
  the sheet (`SHEET_COLUMNS`) have fixed, untranslated names for analysis
  scripts; question, field and column names are the export names, so a
  question may not share a sheet details field's name. Chosen sheets can be
  combined into one, in the order picked (`collect(..., chosen=[ids])`): one
  merged sheets row (differing values all kept, `;`-joined) and their table
  rows in turn, numbered on in `combined_row`. Pages aren't linked automatically:
  sheets may be photocopied, so nothing printed can tell copies apart.
  Files and columns can be renamed per form (Export data > Names; `ExportNames`,
  stored by `storage/export_store.py`), keyed by their default names; blank
  keeps the default, and JSON renames only answer keys, not its structure.
  CSV cells go through `spreadsheet_safe` (an apostrophe before anything a
  spreadsheet would run as a formula: values come from handwriting and file
  names), and `write_csv` never writes two files to one name.
- **Mnemonics are checked among controls showing together**: the tests step
  through each answer type and data type, so fields never shown at once (a
  choice list's and a written answer's) may share a letter.
- **Form versions:** `storage/form_store.save_form` updates the latest version
  until `mark_printed` freezes it, then saves create a new version. A printed
  version's definition must never change: scanning a sheet looks up the exact
  version its QR code names with `load_form_version`.
- **Tests never show a real dialog**: an autouse fixture in `tests/conftest.py` makes
  unpatched message boxes fail, because offscreen they would wait forever. Patch the
  helper the code calls (e.g. `ask_save_discard_cancel`) in the test.
- **Installers** (`packaging/`, `.github/workflows/installers.yml`): one
  PyInstaller recipe (`omr-data-collector.spec`) for all three systems, wrapped
  in Inno Setup, a `.dmg` and an AppImage. Each installer is installed on a fresh
  runner that runs `omr-data-collector --self-check` (`self_check.py`: print and
  scan a sheet, drawn by `rendering/page_photo.py` as the tests' sheets are), so a new dependency or data file that the bundle misses fails
  there. Data files the app reads must be added to the spec's `datas`; find them
  from `__file__`, as `i18n.py` does, so they work in both. Workflows pin
  actions to commit hashes and pass values to scripts through `env`, never
  `${{ }}` inside `run:`.
- **Style:** PEP 8 plus OMRChecker v2's conventions and tooling (ruff, pyright, uv,
  pre-commit, Conventional Commits). `ruff.toml` and `pyrightconfig.json` are copied
  from upstream; don't loosen them per file without a reason in a comment.

## Commands

```bash
uv sync                                       # install
uv run omr-data-collector                     # run the app
uv run pytest                                 # tests (Qt runs offscreen)
uv run ruff check --fix && uv run ruff format
uv run pyright
uv run pre-commit run --all-files
```
