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
