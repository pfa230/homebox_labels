"""Vertical layout variant for Avery 5163 labels."""

from __future__ import annotations

from io import BytesIO

import fitz
import qrcode
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import getAscent, getDescent, stringWidth

from fonts import FontSpec, build_font_config
from label_types import LabelContent, LabelGeometry
from .base import LabelTemplate
from .utils import shrink_fit, wrap_text_to_width
from label_templates.utils import wrap_text_to_width_multiline

PAGE_SIZE = letter

LABEL_W = 4.00 * inch
LABEL_H = 2.00 * inch

COLS = 2
ROWS = 5
SLOTS = ROWS * COLS

MARGIN_LEFT = 0.17 * inch
MARGIN_TOP = 0.50 * inch
H_GAP = 0.16 * inch
V_GAP = 0.00 * inch

LABEL_PADDING = 0.1 * inch
QR_SIZE = 0.80 * LABEL_H

SECTION_GAP = 0.1 * inch
LINE_GAP = 0.06 * inch

_FONTS = build_font_config(  # tuned for vertical stack
    family="Inter",
    title_spec=FontSpec(weight=600, size=20),
    content_spec=FontSpec(weight=600, size=26),
    label_spec=FontSpec(weight=500, size=12),
)
LABEL_BOLD_FONT = _FONTS.content.font_name


class Template(LabelTemplate):
    """Vertical stack layout for Avery 5163 sheets."""

    def __init__(self) -> None:
        self._slot_index = 0
        super().__init__()

    @property
    def page_size(self):  # type: ignore[override]
        return PAGE_SIZE

    def reset(self) -> None:  # type: ignore[override]
        self._slot_index = 0

    def next_label_geometry(self) -> LabelGeometry:  # type: ignore[override]
        row = self._slot_index // COLS
        col = self._slot_index % COLS

        _, page_height = PAGE_SIZE

        bottom = (
            page_height
            - MARGIN_TOP
            - LABEL_H
            - row * (LABEL_H + V_GAP)
        )
        top = bottom + LABEL_H
        left = MARGIN_LEFT + col * (LABEL_W + H_GAP)
        right = left + LABEL_W

        on_new_page = self._slot_index % SLOTS == 0
        self._slot_index = (self._slot_index + 1) % SLOTS

        return LabelGeometry(left, bottom, right, top, on_new_page)

    def render_label(
        self,
        content: LabelContent,
    ) -> bytes:  # type: ignore[override]
        buffer = BytesIO()
        canvas_obj = canvas.Canvas(buffer, pagesize=(LABEL_H, LABEL_W))

        bottom = self._render_row_1(canvas_obj, content)
        bottom = self._render_row_2(canvas_obj, content, bottom)
        self._render_row_3(canvas_obj, content, bottom)

        canvas_obj.showPage()
        canvas_obj.save()

        pdf_bytes = buffer.getvalue()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=self.raster_dpi)
            original_png = pix.tobytes("png")

        with Image.open(BytesIO(original_png)) as img:
            rotated = img.rotate(90, expand=True)
            output = BytesIO()
            rotated.save(output, format="PNG")
            return output.getvalue()

    def _render_row_1(
        self,
        canvas_obj: canvas.Canvas,
        content: LabelContent,
    ) -> float:
        width = LABEL_H
        height = LABEL_W

        qr_bottom = height - QR_SIZE - LABEL_PADDING

        qr_buffer = BytesIO()
        qr = qrcode.QRCode(border=0)
        qr.add_data(content.url)
        qr_img = qr.make_image()
        qr_img.save(qr_buffer, kind="PNG")
        qr_buffer.seek(0)

        canvas_obj.drawImage(
            ImageReader(qr_buffer),
            (width - QR_SIZE) / 2,
            qr_bottom,
            width=QR_SIZE,
            height=QR_SIZE,
            preserveAspectRatio=True,
            mask="auto",
        )

        title = content.title.strip() or "N/A"
        title_width = width - 2 * LABEL_PADDING
        title_size = shrink_fit(
            title,
            title_width,
            max_font=_FONTS.title.size,
            min_font=max(_FONTS.title.size * 0.5, 8.0),
            font_name=_FONTS.title.font_name,
        )
        title_baseline = qr_bottom - title_size
        canvas_obj.setFont(_FONTS.title.font_name, title_size)
        canvas_obj.drawCentredString(width / 2.0, title_baseline, title)

        section_top = title_baseline - LABEL_PADDING
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(0, section_top, LABEL_H, section_top)
        return section_top

    def _render_row_2(
        self,
        canvas_obj: canvas.Canvas,
        content: LabelContent,
        top: float
    ) -> float:
        width = LABEL_H
        bottom = (top + LABEL_PADDING) / 2
        region_height = top - bottom

        body = content.content.strip()
        content_font = _FONTS.content
        if body:
            chosen_lines, chosen_size = wrap_text_to_width_multiline(
                text=body,
                font_name=content_font.font_name,
                font_size=content_font.size,
                max_width_pt=width - 2 * LABEL_PADDING,
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

    def _render_row_3(
        self,
        canvas_obj: canvas.Canvas,
        content: LabelContent,
        height: float
    ):
        width = LABEL_H

        info_cursor = height - SECTION_GAP
        available_width = width - 2 * LABEL_PADDING

        labels_text = content.labels_text.strip()
        if labels_text:
            info_cursor = self._draw_text_block(
                canvas_obj,
                labels_text,
                info_cursor,
                LABEL_PADDING,
                available_width,
                LABEL_BOLD_FONT,
            )
            info_cursor -= SECTION_GAP / 2.0

        if info_cursor >= _FONTS.label.size:
            description_text = content.description_text.strip()
            if description_text:
                info_cursor = self._draw_text_block(
                    canvas_obj,
                    description_text,
                    info_cursor,
                    LABEL_PADDING,
                    available_width,
                    _FONTS.label.font_name,
                )

    def _draw_text_block(
        self,
        canvas_obj: canvas.Canvas,
        text: str,
        cursor: float,
        left: float,
        max_width: float,
        font_name: str,
    ) -> float:
        text = text.strip()
        if not text:
            return cursor

        font_size = _FONTS.label.size
        lines = list(
            wrap_text_to_width(
                text=text,
                font_name=font_name,
                font_size=font_size,
                max_width_pt=max_width,
            )
        )

        if not lines:
            return cursor

        normalized = " ".join(text.split())
        reconstructed = " ".join(lines)
        truncated_wrap = reconstructed.strip() != normalized.strip()

        line_gap = LINE_GAP
        probe_baseline = cursor
        visible_lines: list[str] = []
        for idx, line in enumerate(lines):
            next_baseline = probe_baseline - font_size
            if next_baseline < font_size:
                break
            visible_lines.append(line)
            probe_baseline = next_baseline
            if idx < len(lines) - 1:
                probe_baseline -= line_gap

        if not visible_lines:
            return cursor

        truncated_space = len(visible_lines) < len(lines)
        truncated = truncated_wrap or truncated_space

        if truncated:
            ellipsis = "…"
            ell_width = stringWidth(ellipsis, font_name, font_size)
            if ell_width <= max_width:
                last = visible_lines[-1].rstrip()
                while last and stringWidth(last + ellipsis, font_name, font_size) > max_width:
                    last = last[:-1]
                if last:
                    visible_lines[-1] = last + ellipsis
                else:
                    visible_lines[-1] = (
                        ellipsis if ell_width <= max_width else visible_lines[-1]
                    )

        draw_baseline = cursor
        for idx, line in enumerate(visible_lines):
            draw_baseline -= font_size
            if draw_baseline < font_size:
                break
            canvas_obj.setFont(font_name, font_size)
            canvas_obj.drawString(left, draw_baseline, line.rstrip())
            if idx < len(visible_lines) - 1:
                draw_baseline -= line_gap

        baseline = draw_baseline

        baseline -= SECTION_GAP / 2.0
        return baseline
