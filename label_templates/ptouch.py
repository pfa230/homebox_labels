"""Brother PTouch 24mm label template."""

from __future__ import annotations

from io import BytesIO

import fitz
import qrcode
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from fonts import FontSpec, build_font_config
from label_types import LabelContent, LabelGeometry
from .base import LabelTemplate, TemplateOption
from .utils import shrink_fit, wrap_text_to_width_multiline

LABEL_HEIGHT = 18 * mm
QR_TEXT_GAP = 1 * mm
LABEL_MARGIN_LEFT = 3 * mm
LABEL_MARGIN_RIGHT = 3 * mm

MAX_WIDTH = 75 * mm
MIN_WIDTH = 30 * mm
TEXT_GAP = 1 * mm

FONT_SIZE_TITLE = 14
MAX_FONT_SIZE_CONTENT = 24
MIN_FONT_SIZE_CONTENT = 10

_FONTS = build_font_config(
    family="Inter",
    title_spec=FontSpec(weight=600, size=FONT_SIZE_TITLE),
    content_spec=FontSpec(weight=400, size=MAX_FONT_SIZE_CONTENT),
    label_spec=FontSpec(weight=400, size=12),
)


class Template(LabelTemplate):
    """Stateful template for Brother P-Touch continuous tape."""

    def __init__(self) -> None:
        super().__init__()

    def available_options(self) -> list[TemplateOption]:  # type: ignore[override]
        return []

    @property
    def raster_dpi(self) -> int:  # type: ignore[override]
        return 180

    def reset(self) -> None:  # type: ignore[override]
        pass

    def next_label_geometry(self) -> LabelGeometry:
        raise SystemError("Not supported")

    def render_label(
        self,
        content: LabelContent,
    ) -> bytes:  # type: ignore[override]
        width = self._compute_width(content)

        buffer = BytesIO()
        canvas_obj = canvas.Canvas(buffer, pagesize=(width, LABEL_HEIGHT))

        qr_size = LABEL_HEIGHT
        text_area_width = (
            width
            - qr_size
            - QR_TEXT_GAP
            - LABEL_MARGIN_LEFT
            - LABEL_MARGIN_RIGHT
        )

        qr_buffer = BytesIO()
        qr = qrcode.QRCode(border=0)
        qr.add_data(content.url)
        qr_img = qr.make_image()
        qr_img.save(qr_buffer, kind="PNG")
        qr_buffer.seek(0)

        canvas_obj.drawImage(
            ImageReader(qr_buffer),
            LABEL_MARGIN_LEFT,
            0,
            width=qr_size,
            height=qr_size,
            preserveAspectRatio=True,
            mask="auto",
        )

        text_left = LABEL_MARGIN_LEFT + QR_TEXT_GAP + qr_size
        title = content.display_id.strip() or "Unnamed"
        title_size = shrink_fit(
            title,
            text_area_width,
            max_font=_FONTS.title.size,
            min_font=max(_FONTS.title.size * 0.5, 6.0),
            font_name=_FONTS.title.font_name,
        )
        title_baseline = LABEL_HEIGHT - title_size
        canvas_obj.setFont(_FONTS.title.font_name, title_size)
        canvas_obj.drawString(text_left, title_baseline, title)

        body_text = content.name.strip()
        if body_text:
            available_height = title_baseline - TEXT_GAP
            body_lines, body_size = self._wrap_content_lines(
                body_text,
                text_area_width,
                available_height,
            )
            if body_lines:
                canvas_obj.setFont(_FONTS.content.font_name, body_size)
                first_baseline = title_baseline - TEXT_GAP - body_size
                canvas_obj.drawString(text_left, first_baseline, body_lines[0])
                if len(body_lines) > 1:
                    second_baseline = first_baseline - TEXT_GAP - body_size
                    canvas_obj.drawString(
                        text_left,
                        second_baseline,
                        body_lines[1],
                    )

        canvas_obj.showPage()
        canvas_obj.save()

        pdf_bytes = buffer.getvalue()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=self.raster_dpi)
            return pix.tobytes("png")

    def _compute_width(self, label: LabelContent) -> float:
        qr_size = LABEL_HEIGHT
        text_lines = [
            label.display_id.strip() or "",
            label.name.strip() or "",
            ", ".join(label.labels).strip() or "",
        ]

        font_cycle = [
            (_FONTS.title.font_name, _FONTS.title.size),
            (_FONTS.content.font_name, _FONTS.content.size),
            (_FONTS.label.font_name, _FONTS.label.size),
        ]

        text_widths: list[float] = []
        for idx, line in enumerate(text_lines):
            if not line:
                text_widths.append(0.0)
                continue
            font_name, font_size = font_cycle[min(idx, len(font_cycle) - 1)]
            text_widths.append(stringWidth(line, font_name, font_size))

        desired_text_width = max(text_widths + [0])
        required = LABEL_MARGIN_LEFT + qr_size + QR_TEXT_GAP + \
            desired_text_width + LABEL_MARGIN_RIGHT
        return min(max(required, MIN_WIDTH), MAX_WIDTH)

    def _wrap_content_lines(
        self,
        text: str,
        max_width: float,
        max_height: float,
    ) -> tuple[list[str], float]:
        """Return up to two lines that satisfy width and height limits."""

        stripped = text.strip()
        if not stripped:
            return [], _FONTS.content.size

        attempt_size = MAX_FONT_SIZE_CONTENT
        step = 0.5

        while attempt_size >= MIN_FONT_SIZE_CONTENT:
            lines, chosen_size = wrap_text_to_width_multiline(
                text=stripped,
                font_name=_FONTS.content.font_name,
                font_size=attempt_size,
                max_width_pt=max_width,
                max_lines=2,
                min_font_size=MIN_FONT_SIZE_CONTENT,
                step=step,
            )
            if lines:
                if len(lines) * (chosen_size + TEXT_GAP) <= max_height:
                    return lines, chosen_size
                attempt_size = chosen_size

            attempt_size -= step

        fallback_size = max(
            MIN_FONT_SIZE_CONTENT,
            min(max_height, MAX_FONT_SIZE_CONTENT),
        )
        return ([stripped], fallback_size)
