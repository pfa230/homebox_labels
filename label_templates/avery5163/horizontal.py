"""Horizontal rendering for Avery 5163 labels."""

from __future__ import annotations

from io import BytesIO

import fitz
import qrcode
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from fonts import FontSpec, build_font_config
from label_types import LabelContent
from .common import (
    COL_1_BOTTOM_PAD,
    COL_1_W,
    COL_2_W,
    LABEL_H,
    LABEL_PADDING,
    LABEL_W,
    QR_SIZE,
)
from ..utils import shrink_fit, wrap_text_to_width

_FONTS = build_font_config(
    family="Inter",
    title_spec=FontSpec(weight=500, size=22),
    content_spec=FontSpec(weight=600, size=24),
    label_spec=FontSpec(weight=500, size=12),
)
LABEL_BOLD_FONT = _FONTS.content.font_name
LABEL_REG_FONT = _FONTS.label.font_name


def render_label(
    content: LabelContent,
    outline: bool,
    raster_dpi: int,
) -> bytes:
    buffer = BytesIO()
    canvas_obj = canvas.Canvas(buffer, pagesize=(LABEL_W, LABEL_H))
    _render_col_1(canvas_obj, content)
    _render_col_2(canvas_obj, content)
    if outline:
        _draw_outline(canvas_obj, LABEL_W, LABEL_H)
    canvas_obj.showPage()
    canvas_obj.save()

    pdf_bytes = buffer.getvalue()
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=raster_dpi)
        return pix.tobytes("png")


def _render_col_1(canvas_obj: canvas.Canvas, content: LabelContent) -> None:
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
        width=QR_SIZE,
        height=QR_SIZE,
        preserveAspectRatio=True,
        mask="auto",
    )


def _render_col_2(canvas_obj: canvas.Canvas, content: LabelContent) -> None:
    content_row_y = LABEL_H * 3 / 4
    info_row_y = LABEL_H / 2

    canvas_obj.line(COL_1_W, 0, COL_1_W, LABEL_H)
    canvas_obj.line(COL_1_W, content_row_y, LABEL_W, content_row_y)

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

    info_y = info_row_y - LABEL_PADDING - _FONTS.label.size
    labels_text = content.labels_text.strip()
    if labels_text and info_y >= _FONTS.label.size:
        info_y = _draw_text_block(
            canvas_obj,
            labels_text,
            info_y,
            text_start_x,
            text_max_width,
            LABEL_BOLD_FONT,
        )
        info_y -= LABEL_PADDING / 2.0

    description_text = content.description_text.strip()
    if description_text and info_y >= _FONTS.label.size:
        _draw_text_block(
            canvas_obj,
            description_text,
            info_y,
            text_start_x,
            text_max_width,
            LABEL_REG_FONT,
        )


def _draw_text_block(
    canvas_obj: canvas.Canvas,
    text: str,
    baseline: float,
    text_start_x: float,
    text_max_width: float,
    font_name: str,
) -> float:
    text = text.strip()
    if not text or baseline < _FONTS.label.size:
        return baseline

    font_size = _FONTS.label.size
    lines = list(
        wrap_text_to_width(
            text=text,
            font_name=font_name,
            font_size=font_size,
            max_width_pt=text_max_width,
        )
    )
    if not lines:
        return baseline

    normalized = " ".join(text.split())
    reconstructed = " ".join(lines)
    truncated_wrap = reconstructed.strip() != normalized.strip()

    line_gap = font_size + (LABEL_PADDING / 2.0)
    probe = baseline
    visible_lines: list[str] = []
    for line in lines:
        if probe < font_size:
            break
        visible_lines.append(line)
        probe -= line_gap

    if not visible_lines:
        return baseline

    truncated_space = len(visible_lines) < len(lines)
    truncated = truncated_wrap or truncated_space

    if truncated:
        ellipsis = "…"
        ell_width = stringWidth(ellipsis, font_name, font_size)
        if ell_width <= text_max_width:
            last = visible_lines[-1].rstrip()
            while last and stringWidth(last + ellipsis, font_name, font_size) > text_max_width:
                last = last[:-1]
            if last:
                visible_lines[-1] = last + ellipsis
            else:
                visible_lines[-1] = (
                    ellipsis if ell_width <= text_max_width else visible_lines[-1]
                )

    current = baseline
    for idx, line in enumerate(visible_lines):
        if current < font_size:
            break
        canvas_obj.setFont(font_name, font_size)
        canvas_obj.drawString(text_start_x, current, line.rstrip())
        current -= line_gap
    return current


def _draw_outline(canvas_obj: canvas.Canvas, width: float, height: float) -> None:
    canvas_obj.saveState()
    canvas_obj.setLineWidth(0.75)
    canvas_obj.rect(0, 0, width, height)
    canvas_obj.restoreState()
