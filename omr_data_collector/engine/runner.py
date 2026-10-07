from __future__ import annotations

import csv
from typing import TYPE_CHECKING

# Importing the package first puts the vendored engine on the import path.
import omr_data_collector.engine  # noqa: F401  # isort: skip
from src.entry import entry_point

if TYPE_CHECKING:
    from pathlib import Path


def run_omr(input_dir: Path, output_dir: Path) -> list[dict[str, str]]:
    """Read every sheet under ``input_dir`` with OMRChecker.

    ``input_dir`` must hold a ``template.json`` (and optionally a ``config.json``)
    in OMRChecker v2's format, next to the sheet images or in a parent directory.

    Args:
        input_dir: Directory of sheet images to read.
        output_dir: Where OMRChecker writes its CSVs and annotated images.

    Returns:
        One row per successfully read sheet, keyed by the CSV column names.
    """
    args = {
        "debug": True,
        "input_paths": [str(input_dir)],
        "output_dir": str(output_dir),
        "setLayout": False,
        "outputMode": "default",
    }
    entry_point(input_dir, args)

    rows: list[dict[str, str]] = []
    # OMRChecker mirrors the input tree, writing a Results/ directory per folder of
    # images, with a time-stamped file name.
    for results_csv in sorted(output_dir.glob("**/Results/*.csv")):
        with results_csv.open(newline="") as results_file:
            rows.extend(csv.DictReader(results_file))
    return rows
