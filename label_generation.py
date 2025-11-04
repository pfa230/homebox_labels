"""Rendering helpers for Homebox label output."""

from __future__ import annotations

from io import BytesIO
from typing import Sequence

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from label_types import LabelContent
from label_templates.base import LabelTemplate


def render(
    output_path: str | None,
    template: LabelTemplate,
    labels: Sequence[LabelContent],
    skip: int,
    draw_outline: bool,
) -> str:
    """Render labels to either PDF or PNG output depending on template type."""

    template.reset()
    if template.page_size:
        return render_pdf(output_path, template, labels, skip, draw_outline)
    if draw_outline:
        raise SystemExit("--draw-outline is not compatible with non-PDF templates.")
    if skip > 0:
        raise SystemExit("--skip is not compatible with non-PDF templates.")
    return render_png(output_path, template, labels)


def render_png(
    output_path: str | None,
    template: LabelTemplate,
    labels: Sequence[LabelContent],
) -> str:
    """Render each label as a standalone PNG."""

    output_path = output_path or "locations"

    template.reset()

    if len(labels) == 0:
        return "No labels matched the provided filters; no output generated."

    for i, label in enumerate(labels):
        png_bytes = template.render_label(label)

        png_name = f"{output_path}_{(i + 1):02d}.png"
        with open(png_name, "wb") as handle:
            handle.write(png_bytes)

    return f"Wrote {len(labels)} PNG files with prefix '{output_path}_'."


def render_pdf(
    output_path: str | None,
    template: LabelTemplate,
    labels: Sequence[LabelContent],
    skip: int,
    draw_outline: bool,
) -> str:
    """Render labels to a multi-page PDF."""

    output_path = output_path or "locations.pdf"

    template.reset()

    canvas_obj = canvas.Canvas(output_path, pagesize=template.page_size)

    for _ in range(skip):
        template.next_label_geometry()

    first_page = True
    for label in labels:
        geometry = template.next_label_geometry()
        if geometry.on_new_page:
            if first_page:
                first_page = False
            else:
                canvas_obj.showPage()

        if geometry.width <= 0 or geometry.height <= 0:
            raise SystemError(
                "Template produced non-positive geometry dimensions."
            )

        png_bytes = template.render_label(label)
        image_reader = ImageReader(BytesIO(png_bytes))
        canvas_obj.drawImage(
            image_reader,
            geometry.left,
            geometry.bottom,
            width=geometry.width,
            height=geometry.height,
            mask="auto",
        )

        if draw_outline:
            canvas_obj.saveState()
            canvas_obj.setLineWidth(0.5)
            canvas_obj.rect(
                geometry.left,
                geometry.bottom,
                geometry.width,
                geometry.height,
            )
            canvas_obj.restoreState()

    canvas_obj.showPage()
    canvas_obj.save()
    return f"Wrote {output_path}"
