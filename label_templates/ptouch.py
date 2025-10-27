"""Brother PTouch 24mm label template."""

from __future__ import annotations

from io import BytesIO

import qrcode
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from fonts import FontSpec, build_font_config
from label_types import LabelContent, LabelGeometry
from .base import LabelTemplate
from .utils import shrink_fit, wrap_text_to_width

LABEL_HEIGHT = 24 * mm
MAX_WIDTH = 100 * mm
MIN_WIDTH = 30 * mm
LABEL_PADDING = 2 * mm
TEXT_GAP = 1.5 * mm

_FONTS = build_font_config(
    family="Inter",
    title_spec=FontSpec(weight=500, size=20),
    content_spec=FontSpec(weight=600, size=20),
    label_spec=FontSpec(weight=500, size=12),
)


def _compute_width(label: LabelContent) -> float:
    qr_size = LABEL_HEIGHT - 2 * LABEL_PADDING
    text_lines = [
        label.title.strip() or "",
        label.content.strip() or "",
        label.categories_text.strip() or "",
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

    desired_text_width = max(text_widths + [0]) + LABEL_PADDING
    required = LABEL_PADDING + qr_size + LABEL_PADDING + desired_text_width
    return min(max(required, MIN_WIDTH), MAX_WIDTH)


class Template(LabelTemplate):
    """Stateful template for Brother P-Touch continuous tape."""

    def __init__(self) -> None:
        super().__init__()

    def reset(self) -> None:  # type: ignore[override]
        self._page_break_pending = False

    def next_label_geometry(
        self,
        label: LabelContent | None,
    ) -> LabelGeometry:  # type: ignore[override]
        if not label:
            raise SystemError("Missing label content")

        width = _compute_width(label)
        self._page_break_pending = True
        return LabelGeometry(0.0, 0.0, width, LABEL_HEIGHT)

    def consume_page_break(self) -> bool:  # type: ignore[override]
        pending = self._page_break_pending
        self._page_break_pending = False
        return pending

    def draw_label(
        self,
        canvas_obj: canvas.Canvas,
        content: LabelContent,
        *,
        geometry: LabelGeometry,
    ) -> None:  # type: ignore[override]
        width = geometry.width
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
        title_baseline = LABEL_HEIGHT - LABEL_PADDING - title_size
        canvas_obj.setFont(_FONTS.title.font_name, title_size)
        canvas_obj.drawString(text_left, title_baseline, title)

        body_text = content.content.strip()
        if body_text:
            body_size = shrink_fit(
                body_text,
                text_area_width,
                max_font=_FONTS.content.size,
                min_font=max(_FONTS.content.size * 0.5, 6.0),
                font_name=_FONTS.content.font_name,
            )
            body_baseline = title_baseline - TEXT_GAP - body_size
            canvas_obj.setFont(_FONTS.content.font_name, body_size)
            canvas_obj.drawString(text_left, body_baseline, body_text)
