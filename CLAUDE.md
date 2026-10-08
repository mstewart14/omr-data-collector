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
    every label and button a unique Alt+letter mnemonic;
  - say "(required)" in the label, never only in a placeholder;
  - show errors as text in a hidden-until-needed form row
    (`accessibility.set_field_error`), set them as the field's accessible
    description, and move focus to the first invalid field;
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
- **Pages** in `MainWindow` provide `status_message`, `has_unsaved_changes()`,
  `save()` and `initial_focus`; the window handles section switching (Ctrl+1, 2, …)
  and the unsaved-changes prompt on close.
- **Block libraries** (text blocks, questions, and next tables) subclass
  `ui/LibraryPage.py`, which owns the list, New/Duplicate/Delete, the name field,
  Save/Revert and unsaved-change prompts; a subclass adds its fields in
  `build_fields` and says how to read, load, store and copy its item. How an answer
  is collected (yes/no, one or many choices, written) is an `AnswerSpec`, edited by
  `ui/AnswerFields.py`, which adds its rows to the page's own form; table columns
  reuse both.
- **Forms keep their own copy of every block** (wiki 50011-50012): editing a
  library block later asks "going forward only" or "everywhere", and "everywhere"
  makes new form versions so sheets already printed still scan.
- **Tests never show a real dialog**: an autouse fixture in `tests/conftest.py` makes
  unpatched message boxes fail, because offscreen they would wait forever. Patch the
  helper the code calls (e.g. `ask_save_discard_cancel`) in the test.
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
