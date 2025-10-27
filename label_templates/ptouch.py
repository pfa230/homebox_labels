"""Brother PTouch 24mm label template."""

from __future__ import annotations

from io import BytesIO
from typing import List

import qrcode
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from fonts import FontSpec, build_font_config
from label_types import LabelContent, LabelGeometry
from .utils import shrink_fit, wrap_text_to_width

LABEL_HEIGHT = 24 * mm
MAX_WIDTH = 100 * mm
MIN_WIDTH = 30 * mm
LABEL_PADDING = 2 * mm
TEXT_GAP = 1.5 * mm

_FONTS = build_font_config(
    family="Inter",
    title_spec=FontSpec(weight=700, size=18),
    content_spec=FontSpec(weight=500, size=14),
    label_spec=FontSpec(weight=500, size=12),
)


def _compute_width(label: LabelContent) -> float:
    qr_size = LABEL_HEIGHT - 2 * LABEL_PADDING
    text_lines = [
        label.title.strip() or "",
        label.content.strip() or "",
        label.categories_text.strip() or "",
    ]
    text_widths = [
        stringWidth(line, _FONTS.title.font_name, _FONTS.title.size)
        if idx == 0
        else stringWidth(line, _FONTS.content.font_name if idx == 1 else _FONTS.label.font_name,
                         _FONTS.content.size if idx == 1 else _FONTS.label.size)
        for idx, line in enumerate(text_lines)
    ]
    desired_text_width = max(text_widths + [0]) + LABEL_PADDING
    required = LABEL_PADDING + qr_size + LABEL_PADDING + desired_text_width
    return min(max(required, MIN_WIDTH), MAX_WIDTH)


def get_label_geometry(label: LabelContent) -> LabelGeometry:
    width = _compute_width(label)
    return LabelGeometry(0.0, 0.0, width, LABEL_HEIGHT)


def get_label_grid() -> List[LabelGeometry]:
    geom = get_label_geometry(LabelContent("", "", ""))
    return [geom]


def draw_label(
    canvas_obj: canvas.Canvas,
    content: LabelContent,
    *,
    geometry: LabelGeometry | None = None,
) -> None:
    width = geometry.width if geometry else MAX_WIDTH
    qr_size = LABEL_HEIGHT - 2 * LABEL_PADDING
    text_area_width = max(width - qr_size - 3 * LABEL_PADDING, 0)

    buffer = BytesIO()
    qr = qrcode.QRCode(border=0)
    qr.add_data(content.url)
    qr_img = qr.make_image()
    qr_img.save(buffer, kind="PNG")
    buffer.seek(0)

    canvas_obj.drawImage(
        ImageReader(buffer),
        LABEL_PADDING,
        LABEL_PADDING,
        width=qr_size,
        height=qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )

    text_left = LABEL_PADDING * 2 + qr_size

    title = content.title.strip() or "Unnamed"
    title_size = shrink_fit(
        title,
        text_area_width,
        max_font=_FONTS.title.size,
        min_font=max(_FONTS.title.size * 0.5, 6.0),
        font_name=_FONTS.title.font_name,
    )
    canvas_obj.setFont(_FONTS.title.font_name, title_size)
    canvas_obj.drawString(text_left, LABEL_HEIGHT - LABEL_PADDING - title_size, title)

    body_text = content.content.strip()
    if body_text:
        body_size = shrink_fit(
            body_text,
            text_area_width,
            max_font=_FONTS.content.size,
            min_font=max(_FONTS.content.size * 0.5, 6.0),
            font_name=_FONTS.content.font_name,
        )
        canvas_obj.setFont(_FONTS.content.font_name, body_size)
        canvas_obj.drawString(
            text_left,
            LABEL_HEIGHT - LABEL_PADDING - title_size - TEXT_GAP - body_size,
            body_text,
        )

    tags = content.categories_text.strip()
    if tags:
        tag_lines = wrap_text_to_width(
            tags,
            _FONTS.label.font_name,
            _FONTS.label.size,
            text_area_width,
        )
        y = LABEL_PADDING
        canvas_obj.setFont(_FONTS.label.font_name, _FONTS.label.size)
        for line in tag_lines:
            canvas_obj.drawString(text_left, y, line)
            y += _FONTS.label.size + TEXT_GAP
