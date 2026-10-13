"""The check the installer builds run against each installed app."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from omr_data_collector import self_check

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.usefixtures("qapp")


def test_the_self_check_reads_back_its_sheet(tmp_path: Path) -> None:
    report = tmp_path / "report.txt"

    status = self_check.run(report)

    outcome = report.read_text(encoding="utf-8")
    assert status == 0, outcome
    assert outcome.startswith("ok: read ('green',)")


def test_a_failing_self_check_reports_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(self_check, "MARKED", 5)
    report = tmp_path / "report.txt"

    assert self_check.run(report) == 1

    assert "IndexError" in report.read_text(encoding="utf-8")
