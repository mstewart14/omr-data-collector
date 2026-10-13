from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import cv2
import numpy as np

# Importing the package first puts the vendored engine on the import path.
import omr_data_collector.engine  # noqa: F401  # isort: skip
from src.algorithm.template.template import Template
from src.entry import entry_point
from src.utils.image import ImageUtils
from src.utils.parsing import open_config_with_defaults

if TYPE_CHECKING:
    from pathlib import Path

    from dotmap import DotMap

TEMPLATE_FILE_NAME = "template.json"
CONFIG_FILE_NAME = "config.json"


@dataclass(frozen=True)
class MeasuredBubble:
    """One bubble as OMRChecker measured it on the straightened page.

    ``index`` is its place in its field, left to right; ``mean`` its average
    grey (0 black, 255 white); ``rect`` its x, y, width and height in template
    pixels.
    """

    field_label: str
    index: int
    mean: float
    rect: tuple[int, int, int, int]


@dataclass(frozen=True)
class MeasuredPage:
    """A page straightened on its markers, at template size, and its bubbles."""

    image: np.ndarray
    bubbles: tuple[MeasuredBubble, ...]


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


def measure_page(input_dir: Path, image_path: Path, output_dir: Path) -> MeasuredPage:
    """Straighten one sheet with OMRChecker and measure every bubble on it.

    Uses ``input_dir``'s template and config, as ``run_omr`` does, but leaves
    deciding which bubbles are marked to the caller: OMRChecker's own decision
    compares bubbles across the whole page, which a page lit unevenly or marked
    lightly can defeat (see ``engine.marks``).

    Raises:
        ValueError: OMRChecker couldn't find the page or its corner markers.
    """
    args = {
        "debug": True,
        "input_paths": [str(input_dir)],
        "output_dir": str(output_dir),
        "setLayout": False,
        "outputMode": "default",
    }
    # OMRChecker's config is a DotMap, though typed as the dict it's read from.
    config = cast(
        "DotMap", open_config_with_defaults(input_dir / CONFIG_FILE_NAME, args)
    )
    template = Template(input_dir / TEMPLATE_FILE_NAME, config)
    template.reset_and_setup_for_directory(output_dir)
    template.save_image_ops.reset_all_save_img()
    gray, colored = ImageUtils.read_image_util(image_path, config)
    gray, colored, template = template.apply_preprocessors(image_path, gray, colored)
    if gray is None:
        msg = "page or markers not found"
        raise ValueError(msg)
    template.read_omr_response(gray, colored, image_path)
    _, interpretations = template.get_omr_metrics_for_file(str(image_path))
    bubbles = []
    for interpretation in interpretations.values():
        for index, measured in enumerate(interpretation.field_bubble_means):
            box = measured.item_reference
            width, height = box.bubble_dimensions
            x, y = box.get_shifted_position()
            bubbles.append(
                MeasuredBubble(
                    field_label=box.field_label,
                    index=index,
                    mean=float(measured.mean_value),
                    rect=(int(x), int(y), int(width), int(height)),
                )
            )
    # The same image OMRChecker measured: resized to the template, then
    # stretched to full contrast (as Template.read_omr_response does).
    width, height = template.template_dimensions
    resized = cv2.resize(cast("np.ndarray", gray), (int(width), int(height)))
    page = cv2.normalize(resized, np.empty_like(resized), 0, 255, cv2.NORM_MINMAX)
    return MeasuredPage(image=page, bubbles=tuple(bubbles))
