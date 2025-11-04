"""Vertical rendering for Avery 5163 labels."""

from __future__ import annotations

from io import BytesIO

import fitz
import qrcode
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import getAscent, getDescent
from reportlab.pdfgen import canvas

from fonts import FontSpec, build_font_config
from label_types import LabelContent
from .common import (
    LABEL_H,
    LABEL_W,
    VERT_LABEL_PADDING,
    VERT_LINE_GAP,
    VERT_QR_SIZE,
    VERT_SECTION_GAP,
)
from ..utils import shrink_fit, wrap_text_to_width_multiline

_V_FONTS = build_font_config(
    family="Inter",
    title_spec=FontSpec(weight=600, size=20),
    content_spec=FontSpec(weight=600, size=26),
    label_spec=FontSpec(weight=500, size=12),
)
VERT_TITLE_FONT = _V_FONTS.title
VERT_CONTENT_FONT = _V_FONTS.content
VERT_LABEL_FONT = _V_FONTS.label


def render_label(
    content: LabelContent,
    outline: bool,
    raster_dpi: int,
) -> bytes:
    buffer = BytesIO()
    canvas_obj = canvas.Canvas(buffer, pagesize=(LABEL_H, LABEL_W))

    bottom = _render_row_1(canvas_obj, content)
    bottom = _render_row_2(canvas_obj, content, bottom)
    _render_row_3(canvas_obj, content, bottom)

    if outline:
        _draw_outline(canvas_obj, LABEL_H, LABEL_W)

    canvas_obj.showPage()
    canvas_obj.save()

    pdf_bytes = buffer.getvalue()
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=raster_dpi)
        original_png = pix.tobytes("png")

    with Image.open(BytesIO(original_png)) as img:
        rotated = img.rotate(90, expand=True)
        output = BytesIO()
        rotated.save(output, format="PNG")
        return output.getvalue()


def _render_row_1(canvas_obj: canvas.Canvas, content: LabelContent) -> float:
    width = LABEL_H
    height = LABEL_W

    qr_bottom = height - VERT_QR_SIZE - VERT_LABEL_PADDING

    qr_buffer = BytesIO()
    qr = qrcode.QRCode(border=0)
    qr.add_data(content.url)
    qr_img = qr.make_image()
    qr_img.save(qr_buffer, kind="PNG")
    qr_buffer.seek(0)

    canvas_obj.drawImage(
        ImageReader(qr_buffer),
        (width - VERT_QR_SIZE) / 2,
        qr_bottom,
        width=VERT_QR_SIZE,
        height=VERT_QR_SIZE,
        preserveAspectRatio=True,
        mask="auto",
    )

    title = content.display_id.strip() or "N/A"
    title_width = width - 2 * VERT_LABEL_PADDING
    title_size = shrink_fit(
        title,
        title_width,
        max_font=VERT_TITLE_FONT.size,
        min_font=max(VERT_TITLE_FONT.size * 0.5, 8.0),
        font_name=VERT_TITLE_FONT.font_name,
    )
    title_baseline = qr_bottom - title_size
    canvas_obj.setFont(VERT_TITLE_FONT.font_name, title_size)
    canvas_obj.drawCentredString(width / 2.0, title_baseline, title)

    section_top = title_baseline - VERT_LABEL_PADDING
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(0, section_top, LABEL_H, section_top)
    return section_top


def _render_row_2(canvas_obj: canvas.Canvas, content: LabelContent, top: float) -> float:
    width = LABEL_H
    bottom = (top + VERT_LABEL_PADDING) / 2
    region_height = top - bottom

    body = content.name.strip()
    content_font = VERT_CONTENT_FONT
    if body:
        chosen_lines, chosen_size = wrap_text_to_width_multiline(
            text=body,
            font_name=content_font.font_name,
            font_size=content_font.size,
            max_width_pt=width - 2 * VERT_LABEL_PADDING,
            max_lines=2,
            min_font_size=max(content_font.size * 0.5, 8.0),
            step=0.5,
        )

        if chosen_lines:
            canvas_obj.setFont(content_font.font_name, chosen_size)
            ascent = (
                getAscent(content_font.font_name)
                / 1000.0
                * chosen_size
            )
            descent = (
                abs(getDescent(content_font.font_name))
                / 1000.0
                * chosen_size
            )
            line_height = (ascent + descent) * 0.9
            block_height = len(chosen_lines) * line_height
            offset = max((region_height - block_height) / 2.0, 0.0)
            top_of_block = top - offset
            baseline = top_of_block - ascent
            for line in chosen_lines:
                canvas_obj.drawCentredString(width / 2.0, baseline, line)
                baseline -= line_height

    canvas_obj.line(0, bottom, LABEL_H, bottom)
    return bottom


def _render_row_3(canvas_obj: canvas.Canvas, content: LabelContent, height: float) -> None:
    width = LABEL_H

    info_cursor = height - VERT_SECTION_GAP
    sections: list[tuple[str, int]] = [
        (content.description.strip(), 3),
        (", ".join(content.labels).strip(), 2),
    ]

    for text, max_lines in sections:
        if not text:
            continue
        lines, line_size = wrap_text_to_width_multiline(
            text=text,
            font_name=VERT_LABEL_FONT.font_name,
            font_size=VERT_LABEL_FONT.size,
            max_width_pt=width - 2 * VERT_LABEL_PADDING,
            max_lines=max_lines,
            min_font_size=max(VERT_LABEL_FONT.size * 0.5, 8.0),
            step=0.5,
        )
        if not lines:
            continue

        canvas_obj.setFont(VERT_LABEL_FONT.font_name, line_size)
        for line in lines:
            info_cursor -= line_size
            canvas_obj.drawCentredString(width / 2.0, info_cursor, line)
        info_cursor -= VERT_LINE_GAP


def _draw_outline(canvas_obj: canvas.Canvas, width: float, height: float) -> None:
    canvas_obj.saveState()
    canvas_obj.setLineWidth(0.75)
    canvas_obj.rect(0, 0, width, height)
    canvas_obj.restoreState()
