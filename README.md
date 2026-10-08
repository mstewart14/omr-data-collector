# OMR Data Collector

A desktop app (macOS, Windows, Linux) for service providers who collect data on paper:

1. **Build** printable forms from reusable blocks: text, questions and tables of
   bubble or hand-written fields, with a QR code naming the organization and form.
2. **Capture** photos or scans of the filled-in forms, read the bubbles with
   [OMRChecker](https://github.com/Udayraj123/OMRChecker), and let staff check the
   result against the image and key in hand-written fields.
3. **Export** the data as CSV or JSON.

A separate, capture-only mobile app may come later.

Product epics and user stories live on the team wiki:
<https://docs.stewartclan.ca/OMR%20Data%20Collector>.

## Getting started

Needs [uv](https://docs.astral.sh/uv/) and, for QR/barcode reading, the system zbar
library (`apt install libzbar0`, `brew install zbar`; bundled with the Windows wheel).
On Apple Silicon Macs, also `export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib"`
so Python can find Homebrew's zbar.

```bash
uv sync
uv run pre-commit install --install-hooks
uv run omr-data-collector     # or: uv run python -m omr_data_collector
```

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
versions OMRChecker pins (see the comment there for the two deliberate differences).

OMRChecker is © Udayraj Deshmukh and contributors, MIT licensed
(`vendor/omrchecker/LICENSE`).
