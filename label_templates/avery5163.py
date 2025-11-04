"""Avery 5163 label template implementation."""

from __future__ import annotations

from io import BytesIO

import fitz
import qrcode
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from fonts import FontSpec, build_font_config
from label_types import LabelContent, LabelGeometry
from .base import LabelTemplate, TemplateOption
from .utils import shrink_fit, wrap_text_to_width

PAGE_SIZE = letter

LABEL_W = 4.00 * inch
LABEL_H = 2.00 * inch
COL_1_W = 1.5 * inch
COL_2_W = LABEL_W - COL_1_W

COLS = 2
ROWS = 5
SLOTS = ROWS * COLS

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
LABEL_BOLD_FONT = _FONTS.content.font_name
LABEL_REG_FONT = _FONTS.label.font_name


class _HorizontalTemplate(LabelTemplate):
    """Stateful template for Avery 5163 sheets."""

    def __init__(self) -> None:
        self._slot_index = 0
        super().__init__()

    @property
    def page_size(self):  # type: ignore[override]
        return PAGE_SIZE

    def reset(self) -> None:  # type: ignore[override]
        self._slots_per_page = ROWS * COLS
        self._slot_index = 0
        self._page_break_pending = False

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

    def render_label(
        self,
        content: LabelContent,
    ) -> bytes:  # type: ignore[override]
        buffer = BytesIO()
        canvas_obj = canvas.Canvas(buffer, pagesize=(LABEL_W, LABEL_H))
        self._render_col_1(canvas_obj, content)
        self._render_col_2(canvas_obj, content)
        canvas_obj.showPage()
        canvas_obj.save()

        pdf_bytes = buffer.getvalue()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=self.raster_dpi)
            return pix.tobytes("png")

    def consume_page_break(self) -> bool:  # type: ignore[override]
        pending = self._page_break_pending
        self._page_break_pending = False
        return pending

    def _render_col_1(self, canvas_obj: canvas.Canvas, content: LabelContent):
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
        self,
        canvas_obj: canvas.Canvas,
        content: LabelContent,
    ) -> None:
        canvas_obj.setLineWidth(0.5)

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
            info_y = self._draw_text_block(
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
            info_y = self._draw_text_block(
                canvas_obj,
                description_text,
                info_y,
                text_start_x,
                text_max_width,
                LABEL_REG_FONT,
            )

    def _draw_text_block(
        self,
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
        for idx, line in enumerate(lines):
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
            if idx < len(visible_lines) - 1:
                current -= line_gap
        if visible_lines:
            current -= line_gap
        return current


class Template(LabelTemplate):
    """Avery 5163 template supporting per-label orientation options."""

    _DEFAULT_ORIENTATION = "horizontal"

    def __init__(self) -> None:
        self._layout = _HorizontalTemplate()
        from .avery5163_vert import Template as VerticalTemplate

        self._vertical_renderer = VerticalTemplate()
        self._default_orientation = self._DEFAULT_ORIENTATION
        super().__init__()

    def available_options(self) -> list[TemplateOption]:  # type: ignore[override]
        return [
            TemplateOption(
                name="orientation",
                possible_values=["horizontal", "vertical"],
            )
        ]

    def apply_options(self, selections: dict[str, str]) -> None:  # type: ignore[override]
        orientation = (selections.get("orientation") or self._DEFAULT_ORIENTATION).lower()
        if orientation not in {"horizontal", "vertical"}:
            raise ValueError(
                "Invalid orientation option. Choose 'horizontal' or 'vertical'."
            )
        self._default_orientation = orientation

    @property
    def page_size(self):  # type: ignore[override]
        return self._layout.page_size

    @property
    def raster_dpi(self) -> int:  # type: ignore[override]
        return self._layout.raster_dpi

    def reset(self) -> None:  # type: ignore[override]
        self._layout.reset()

    def next_label_geometry(self) -> LabelGeometry:
        return self._layout.next_label_geometry()

    def render_label(self, content: LabelContent) -> bytes:  # type: ignore[override]
        orientation = self._resolve_orientation(content)
        if orientation == "vertical":
            self._vertical_renderer.reset()
            return self._vertical_renderer.render_label(content)
        return self._layout.render_label(content)

    def consume_page_break(self) -> bool:
        consume = getattr(self._layout, "consume_page_break", None)
        if consume:
            return consume()
        return False

    def _resolve_orientation(self, content: LabelContent) -> str:
        options = content.template_options or {}
        orientation = (options.get("orientation") or self._default_orientation).lower()
        if orientation not in {"horizontal", "vertical"}:
            orientation = self._default_orientation
        return orientation
