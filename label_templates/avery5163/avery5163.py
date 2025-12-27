"""Avery 5163 template with per-label orientation and outline options."""

from __future__ import annotations

from enum import StrEnum

from label_templates.label_types import LabelContent, LabelGeometry
from ..base import LabelTemplate, TemplateOption
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
from .horizontal import render_label as render_horizontal_label
from .vertical import render_label as render_vertical_label


class Orientation(StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class Outline(StrEnum):
    OFF = "off"
    ON = "on"


class Template(LabelTemplate):
    """Unified Avery 5163 template supporting per-label options."""

    _DEFAULT_ORIENTATION = Orientation.HORIZONTAL
    _DEFAULT_OUTLINE = Outline.OFF
    _slot_index: int

    def __init__(self) -> None:
        self._slot_index = 0
        super().__init__()

    def available_options(self) -> list[TemplateOption]:
        return [
            TemplateOption(
                name="orientation",
                possible_values=[m.value for m in Orientation],
            ),
            TemplateOption(
                name="outline",
                possible_values=[t.value for t in Outline],
            ),
        ]

    @property
    def page_size(self) -> tuple[float, float]:
        return PAGE_SIZE

    def reset(self) -> None:
        self._slot_index = 0

    def next_label_geometry(self) -> LabelGeometry:
        row = self._slot_index // COLS
        col = self._slot_index % COLS

        _, page_height = PAGE_SIZE

        bottom = (
            page_height
            - MARGIN_TOP
            - LABEL_H
            - row * (LABEL_H + V_GAP)
            + OFFSET_Y
        )
        top = bottom + LABEL_H
        left = MARGIN_LEFT + col * (LABEL_W + H_GAP) + OFFSET_X
        right = left + LABEL_W
        on_new_page = self._slot_index == 0
        self._slot_index = (self._slot_index + 1) % SLOTS

        return LabelGeometry(left, bottom, right, top, on_new_page)

    def render_label(self, content: LabelContent) -> bytes:
        orientation = self._orientation_for_label(content)
        outline = self._outline_for_label(content)
        if orientation is Orientation.VERTICAL:
            return render_vertical_label(content, outline, self.raster_dpi)
        return render_horizontal_label(content, outline, self.raster_dpi)

    def _orientation_for_label(self, content: LabelContent) -> Orientation:
        options = content.template_options or {}
        value = (options.get("orientation") or self._DEFAULT_ORIENTATION.value).lower()
        if value in Orientation._value2member_map_:
            return Orientation(value)
        return self._DEFAULT_ORIENTATION

    def _outline_for_label(self, content: LabelContent) -> bool:
        options = content.template_options or {}
        value = (options.get("outline") or self._DEFAULT_OUTLINE.value).lower()
        if value in Outline._value2member_map_:
            return Outline(value) is Outline.ON
        return self._DEFAULT_OUTLINE is Outline.ON
