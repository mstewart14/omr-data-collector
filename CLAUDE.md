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
  - give each input a `QLabel` buddy that is its sibling in the same layout (that
    sibling relation is how Qt tells screen readers the label), with a unique
    Alt+letter mnemonic;
  - say "(required)" in the label, never only in a placeholder;
  - show errors as text in a hidden-until-needed form row
    (`accessibility.set_field_error`), set them as the field's accessible
    description, and move focus to the first invalid field;
  - send status messages through `MainWindow.show_status`, which also announces
    them to screen readers;
  - give images an accessible name and description;
  - set a tab order that follows the screen;
  - take colors from `accessibility` helpers checked to 4.5:1, re-chosen on
    `PaletteChange`, and size things in font units, not fixed pixels;
  - have tests for all of the above (see `tests/test_accessibility.py`).
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
