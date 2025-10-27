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
from .utils import shrink_fit

LABEL_HEIGHT = 24 * mm
MAX_WIDTH = 100 * mm
MIN_WIDTH = 30 * mm
LABEL_PADDING = 1 * mm
TEXT_GAP = 1 * mm

_FONTS = build_font_config(
    family="Inter",
    title_spec=FontSpec(weight=400, size=16),
    content_spec=FontSpec(weight=600, size=24),
    label_spec=FontSpec(weight=500, size=12),
)

_EMPTY_LABEL = LabelContent("", "", "")


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


def _wrap_content_lines(
    text: str,
    max_width: float,
    max_height: float,
) -> tuple[list[str], float]:
    """Return up to two lines that satisfy width and height limits."""

    stripped = text.strip()
    if not stripped:
        return [], _FONTS.content.size

    words = stripped.split()
    font_name = _FONTS.content.font_name
    max_font = _FONTS.content.size
    min_font = max(max_font * 0.5, 6.0)
    step = 0.5
    size = max_font

    while size >= min_font:
        for split_idx in range(1, len(words) + 1):
            line_one = " ".join(words[:split_idx]).strip()
            remaining = words[split_idx:]

            if line_one and stringWidth(line_one, font_name, size) > max_width:
                break

            lines: list[str] = [line_one] if line_one else []

            if remaining:
                line_two = " ".join(remaining)
                if stringWidth(line_two, font_name, size) > max_width:
                    continue
                lines.append(line_two)

            total_height = (
                len(lines) * size
                + max(0, len(lines) - 1) * TEXT_GAP
            )
            if lines and total_height <= max_height:
                return lines, size

        size -= step

    fallback_line = " ".join(words)
    fallback_size = shrink_fit(
        fallback_line,
        max_width,
        max_font=max_font,
        min_font=min_font,
        font_name=font_name,
    )
    fallback_size = min(fallback_size, max_height)
    return ([fallback_line], fallback_size)


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
        effective_label = label or _EMPTY_LABEL

        width = _compute_width(effective_label)
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
            available_height = title_baseline - TEXT_GAP - LABEL_PADDING
            if available_height > 0:
                body_lines, body_size = _wrap_content_lines(
                    body_text,
                    text_area_width,
                    available_height,
                )
            else:
                body_lines, body_size = [], _FONTS.content.size
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
