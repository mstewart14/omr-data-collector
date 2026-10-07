from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from omr_data_collector.engine import OMRCHECKER_ROOT
from omr_data_collector.engine.runner import run_omr

if TYPE_CHECKING:
    from pathlib import Path


def test_reads_vendored_mobile_camera_sample(tmp_path: Path) -> None:
    # OMRChecker's own sample of a phone photo, so this checks the vendored engine
    # and our pinned dependencies together. Expected values come from upstream's
    # snapshot for the same sample (test_run_omr_marker_mobile).
    input_dir = tmp_path / "input"
    shutil.copytree(OMRCHECKER_ROOT / "samples" / "1-mobile-camera", input_dir)

    rows = run_omr(input_dir, tmp_path / "output")

    assert len(rows) == 1
    row = rows[0]
    assert row["file_id"] == "sheet1.jpg"
    assert row["Roll"] == "E503110026"
    answers = [row[f"q{number}"] for number in range(1, 21)]
    assert answers == [
        "B", "", "D", "B", "6", "11", "20", "7", "16", "B",
        "D", "C", "D", "A", "D", "B", "A", "C", "C", "D",
    ]  # fmt: skip
