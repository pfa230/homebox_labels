"""Avery 5163 label template implementation."""

from __future__ import annotations

from io import BytesIO
from typing import Iterable, List, Sequence, Tuple

import qrcode
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from fonts import FontSpec, build_font_config
from label_content import LabelContent

PAGE_SIZE = letter

LABEL_W = 4.00 * inch
LABEL_H = 2.00 * inch

QR_SIZE = LABEL_H * 0.75

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

LABEL_PADDING = 0.12 * inch
TEXT_BOTTOM_PAD = 0.06 * inch

_FONTS = build_font_config(
    family="Inter",
    title_spec=FontSpec(weight=700, size=22),
    content_spec=FontSpec(weight=600, size=20),
    label_spec=FontSpec(weight=500, size=12),
)


def get_label_grid() -> List[Tuple[float, float, float, float]]:
    """Return rectangles for each label on the page."""

    grid: List[Tuple[float, float, float, float]] = []
    _, page_height = PAGE_SIZE

    for row in range(ROWS):
        bottom = (
            page_height
            - MARGIN_TOP
            - LABEL_H
            - row * (LABEL_H + V_GAP)
            + OFFSET_Y
        )
        top = bottom + LABEL_H
        for col in range(COLS):
            left = MARGIN_LEFT + col * (LABEL_W + H_GAP) + OFFSET_X
            right = left + LABEL_W
            grid.append((left, bottom, right, top))
    return grid


def _wrap_text_to_width(
    text: str,
    font_name: str,
    font_size: float,
    max_width_pt: float,
) -> Iterable[str]:
    if not text or max_width_pt <= 0:
        return []

    words = text.split()
    if not words:
        return []

    lines: List[str] = []
    current: List[str] = []
    for word in words:
        tentative = " ".join(current + [word]) if current else word
        if stringWidth(tentative, font_name, font_size) <= max_width_pt or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _shrink_fit(
    text: str,
    max_width_pt: float,
    max_font: float,
    min_font: float,
    font_name: str,
    step: float = 0.5,
) -> float:
    size = max_font
    step = max(step, 0.25)
    while size >= min_font and stringWidth(text, font_name, size) > max_width_pt:
        size -= step
    return max(size, min_font)


def _draw_qr_image(canvas_obj: canvas.Canvas, url: str):
    qr_size = LABEL_H * 0.75 - 2 * LABEL_PADDING
    qr_bottom = LABEL_PADDING

    buffer = BytesIO()
    qr = qrcode.QRCode(border=0)
    qr.add_data(url)
    qr_img = qr.make_image()
    qr_img.save(buffer, kind="PNG")
    buffer.seek(0)

    canvas_obj.drawImage(
        ImageReader(buffer),
        LABEL_PADDING,
        qr_bottom,
        width=qr_size,
        height=qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )


def _render_label_text(
    canvas_obj: canvas.Canvas,
    content: LabelContent,
) -> None:
    left = QR_SIZE + 2 * LABEL_PADDING
    width = LABEL_W - left

    canvas_obj.saveState()
    canvas_obj.setLineWidth(0.5)

    title_row_y = LABEL_H * 3 / 4
    content_row_y = LABEL_H / 2
    info_row_y = LABEL_H / 4

    canvas_obj.line(left, 0, left, title_row_y)
    canvas_obj.line(0, title_row_y, LABEL_W, title_row_y)
    canvas_obj.line(left, content_row_y, LABEL_W, content_row_y)
    canvas_obj.line(left, info_row_y, LABEL_W, info_row_y)
    canvas_obj.restoreState()

    left_column_width = left
    if left_column_width > LABEL_PADDING:
        label_x = left_column_width / 2.0
        canvas_obj.setFont(_FONTS.label.font_name, _FONTS.label.size)
        heading_positions = [
            ("Title", (LABEL_H + title_row_y) / 2.0),
            ("Content", (title_row_y + content_row_y) / 2.0),
            ("Info", (content_row_y) / 2.0),
        ]
        for text, y in heading_positions:
            canvas_obj.drawCentredString(label_x, y, text)

    text_start_x = max(left + LABEL_PADDING, LABEL_PADDING)
    text_max_width = max(width - LABEL_PADDING, 0.0)

    title = content.title.strip() or "Unnamed"
    title_max = _FONTS.title.size
    title_min = max(title_max * 0.5, 8.0)
    title_size = _shrink_fit(
        title,
        text_max_width,
        max_font=title_max,
        min_font=title_min,
        font_name=_FONTS.title.font_name,
    )
    title_y = title_row_y + TEXT_BOTTOM_PAD
    canvas_obj.setFont(_FONTS.title.font_name, title_size)
    canvas_obj.drawString(text_start_x, title_y, title)

    body_text = content.content.strip()
    if body_text:
        body_max = _FONTS.content.size
        body_min = max(body_max * 0.5, 6.0)
        body_size = _shrink_fit(
            body_text,
            text_max_width,
            max_font=body_max,
            min_font=body_min,
            font_name=_FONTS.content.font_name,
        )
        body_y = content_row_y + TEXT_BOTTOM_PAD
        canvas_obj.setFont(_FONTS.content.font_name, body_size)
        canvas_obj.drawString(text_start_x, body_y, body_text)

    info_lines: List[str] = []

    def append_info(prefix: str, value: str) -> None:
        if not value:
            return
        text = f"{prefix}{value.strip()}"
        info_lines.extend(
            _wrap_text_to_width(
                text=text,
                font_name=_FONTS.label.font_name,
                font_size=_FONTS.label.size,
                max_width_pt=text_max_width,
            )
        )

    append_info("Path: ", content.path_text)
    append_info("Tags: ", content.categories_text)
    append_info("URL: ", content.url)

    if info_lines:
        info_y = info_row_y - TEXT_BOTTOM_PAD - _FONTS.label.size
        canvas_obj.setFont(_FONTS.label.font_name, _FONTS.label.size)
        for line in info_lines:
            if info_y < _FONTS.label.size:
                break
            canvas_obj.drawString(text_start_x, info_y, line)
            info_y -= _FONTS.label.size + (TEXT_BOTTOM_PAD / 2.0)


def draw_label(
    canvas_obj: canvas.Canvas,
    content: LabelContent,
) -> None:
    qr_size = LABEL_H * 0.75 - 2 * LABEL_PADDING
    _draw_qr_image(canvas_obj, content.url)
    _render_label_text(canvas_obj, content)
