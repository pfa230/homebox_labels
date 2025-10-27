"""Avery 5163 label template implementation."""

from __future__ import annotations

from io import BytesIO

import qrcode
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from fonts import FontSpec, build_font_config
from label_types import LabelContent, LabelGeometry
from .base import LabelTemplate
from .utils import shrink_fit, wrap_text_to_width

PAGE_SIZE = letter

LABEL_W = 4.00 * inch
LABEL_H = 2.00 * inch
COL_1_W = 1.5 * inch
COL_2_W = LABEL_W - COL_1_W

COLS = 2
ROWS = 5

MARGIN_LEFT = 0.17 * inch
MARGIN_RIGHT = 0.17 * inch
MARGIN_TOP = 0.50 * inch
MARGIN_BOTTOM = 0.50 * inch

H_GAP = 0.16 * inch
V_GAP = 0.00 * inch

OFFSET_X = 0.00 * inch
OFFSET_Y = 0.00 * inch

LABEL_PADDING = 0.1 * inch
COL_1_BOTTOM_PAD = 0.15 * inch

QR_SIZE = COL_1_W - 2 * LABEL_PADDING

_FONTS = build_font_config(
    family="Inter",
    title_spec=FontSpec(weight=500, size=22),
    content_spec=FontSpec(weight=600, size=24),
    label_spec=FontSpec(weight=500, size=12),
)


def _render_col_1(canvas_obj: canvas.Canvas, content: LabelContent):
    qr_size = COL_1_W - 2 * LABEL_PADDING

    title = content.title.strip() or "N/A"
    text_width = COL_1_W - 2 * LABEL_PADDING
    title_max = _FONTS.title.size
    title_min = max(title_max * 0.5, 8.0)
    title_size = shrink_fit(
        title,
        text_width,
        max_font=title_max,
        min_font=title_min,
        font_name=_FONTS.title.font_name,
    )
    center_x = COL_1_W / 2.0
    canvas_obj.setFont(_FONTS.title.font_name, title_size)
    canvas_obj.drawCentredString(center_x, COL_1_BOTTOM_PAD, title)

    title_top = COL_1_BOTTOM_PAD + title_size
    qr_size = COL_1_W - 2 * LABEL_PADDING

    buffer = BytesIO()
    qr = qrcode.QRCode(border=0)
    qr.add_data(content.url)
    qr_img = qr.make_image()
    qr_img.save(buffer, kind="PNG")
    buffer.seek(0)

    canvas_obj.drawImage(
        ImageReader(buffer),
        LABEL_PADDING,
        title_top,
        width=qr_size,
        height=qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )


def _render_col_2(
    canvas_obj: canvas.Canvas,
    content: LabelContent,
) -> None:
    canvas_obj.saveState()
    canvas_obj.setLineWidth(0.5)

    content_row_y = LABEL_H * 3 / 4
    info_row_y = LABEL_H / 2

    canvas_obj.line(COL_1_W, 0, COL_1_W, LABEL_H)
    canvas_obj.line(COL_1_W, content_row_y, LABEL_W, content_row_y)
    canvas_obj.restoreState()

    text_start_x = COL_1_W + LABEL_PADDING
    text_max_width = COL_2_W - 2 * LABEL_PADDING

    content_text = content.content.strip()
    if content_text:
        content_max = _FONTS.content.size
        content_min = max(content_max * 0.5, 6.0)
        content_size = shrink_fit(
            content_text,
            text_max_width,
            max_font=content_max,
            min_font=content_min,
            font_name=_FONTS.content.font_name,
        )
        body_y = content_row_y + LABEL_PADDING
        canvas_obj.setFont(_FONTS.content.font_name, content_size)
        canvas_obj.drawString(text_start_x, body_y, content_text)

    info_lines: list[str] = []

    def append_info(prefix: str, value: str) -> None:
        if not value:
            return
        text = f"{prefix}{value.strip()}"
        info_lines.extend(
            wrap_text_to_width(
                text=text,
                font_name=_FONTS.label.font_name,
                font_size=_FONTS.label.size,
                max_width_pt=text_max_width,
            )
        )

    append_info("Loc: ", content.path_text)
    append_info("Tags: ", content.categories_text)
    append_info("Notes: ", "")

    if info_lines:
        info_y = info_row_y - LABEL_PADDING - _FONTS.label.size
        canvas_obj.setFont(_FONTS.label.font_name, _FONTS.label.size)
        for line in info_lines:
            if info_y < _FONTS.label.size:
                break
            canvas_obj.drawString(text_start_x, info_y, line)
            info_y -= _FONTS.label.size + (LABEL_PADDING / 2.0)


class Template(LabelTemplate):
    """Stateful template for Avery 5163 sheets."""

    def __init__(self) -> None:
        super().__init__()

    @property
    def page_size(self):  # type: ignore[override]
        return PAGE_SIZE

    def reset(self) -> None:  # type: ignore[override]
        self._slots_per_page = ROWS * COLS
        self._slot_index = 0
        self._page_break_pending = False

    def next_label_geometry(
        self,
        label: LabelContent | None,
    ) -> LabelGeometry:  # type: ignore[override]
        _ = label
        slot = self._slot_index
        row = slot // COLS
        col = slot % COLS

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

        self._slot_index = (slot + 1) % max(self._slots_per_page, 1)
        self._page_break_pending = self._slot_index == 0

        return LabelGeometry(left, bottom, right, top)

    def draw_label(
        self,
        canvas_obj: canvas.Canvas,
        content: LabelContent,
    ) -> None:  # type: ignore[override]
        _render_col_1(canvas_obj, content)
        _render_col_2(canvas_obj, content)

    def consume_page_break(self) -> bool:  # type: ignore[override]
        pending = self._page_break_pending
        self._page_break_pending = False
        return pending
