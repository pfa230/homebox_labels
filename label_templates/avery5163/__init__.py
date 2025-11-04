"""Subpackage for Avery 5163 rendering helpers."""

from .horizontal import render_label as render_horizontal_label
from .vertical import render_label as render_vertical_label
from .common import (
    COLS,
    H_GAP,
    LABEL_H,
    LABEL_W,
    MARGIN_LEFT,
    MARGIN_TOP,
    OFFSET_X,
    OFFSET_Y,
    PAGE_SIZE,
    SLOTS,
    V_GAP,
)

__all__ = [
    "render_horizontal_label",
    "render_vertical_label",
    "COLS",
    "H_GAP",
    "LABEL_H",
    "LABEL_W",
    "MARGIN_LEFT",
    "MARGIN_TOP",
    "OFFSET_X",
    "OFFSET_Y",
    "PAGE_SIZE",
    "SLOTS",
    "V_GAP",
]
