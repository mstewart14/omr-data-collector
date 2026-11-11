"""The check the installer builds run against each installed app."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from omr_data_collector import app_version, self_check
from omr_data_collector.storage.pdf_pages import PdfError, PdfPage

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.usefixtures("qapp")


def test_the_self_check_reads_back_its_sheet(tmp_path: Path) -> None:
    report = tmp_path / "report.txt"

    status = self_check.run(report)

    outcome = report.read_text(encoding="utf-8")
    assert status == 0, outcome
    assert outcome.startswith(f"ok: version {app_version()} read ('green',)")
    assert outcome.rstrip().endswith("on a PDF scan's page")


def test_a_failing_self_check_reports_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(self_check, "MARKED", 5)
    report = tmp_path / "report.txt"

    assert self_check.run(report) == 1

    assert "IndexError" in report.read_text(encoding="utf-8")


def test_a_self_check_that_cant_read_pdfs_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As a build missing Qt's PDF support would.
    def no_pdf_support(pdf: Path, _out_dir: Path) -> list[PdfPage]:
        raise PdfError(pdf.name)

    monkeypatch.setattr(self_check, "pdf_page_images", no_pdf_support)
    report = tmp_path / "report.txt"

    assert self_check.run(report) == 1

    assert "PdfError: scan.pdf" in report.read_text(encoding="utf-8")
