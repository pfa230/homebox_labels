#!/usr/bin/env python3
"""Generate Avery 5163 label sheets from Homebox location data."""

import argparse
import os
import re
import sys
import textwrap
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, List, Optional, Sequence, Tuple


from homebox_client.exceptions import ApiException
from dotenv import load_dotenv

import qrcode
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from homebox_api import HomeboxApiManager

# --- Template geometry (in inches) ---
PAGE_W, PAGE_H = letter  # 8.5 x 11 in in points
INCH_PT = inch

LABEL_W = 4.00 * INCH_PT
LABEL_H = 2.00 * INCH_PT

COLS = 2
ROWS = 5

# Margins and gaps chosen to exactly fill 8.5" width and 11" height
# Adjust if your printer shifts: set OFFSET_X, OFFSET_Y below.
MARGIN_LEFT = 0.17 * INCH_PT
MARGIN_RIGHT = 0.17 * INCH_PT
MARGIN_TOP = 0.50 * INCH_PT
MARGIN_BOTTOM = 0.50 * INCH_PT

H_GAP = 0.16 * INCH_PT  # between columns
V_GAP = 0.00 * INCH_PT  # between rows

# Optional printer compensation offsets (positive moves right/up)
OFFSET_X = 0.00 * INCH_PT
OFFSET_Y = 0.00 * INCH_PT

LABEL_PADDING = 0.12 * inch

TITLE_FONT_SIZE = 28
TEXT_BOTTOM_PAD = 0.06 * inch


@dataclass(frozen=True)
class LabelContent:
    """Textual payload to render into a label."""

    title: str
    content: str
    url: str
    path_text: str = ""
    categories_text: str = ""


@dataclass(frozen=True)
class LabelGeometry:
    """Rectangle describing where the label should be plotted."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class _TextColumn:
    """Render-time information on the column reserved for text."""

    left: float
    width: float


@dataclass(frozen=True)
class _TextContext:
    """Shared state for rendering text blocks within a label."""

    canvas: canvas.Canvas
    geometry: LabelGeometry
    column: _TextColumn
    center_x: float


def _filter_locations_by_name(locations: Sequence[Dict], pattern: Optional[str]) -> List[Dict]:
    """Apply the name regex filter declared by the user."""

    if not pattern:
        return list(locations)

    try:
        name_re = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise SystemExit(
            f"Invalid --name-pattern regex '{pattern}': {exc}") from exc

    filtered = []
    for loc in locations:
        name = location_display_text(loc.get("name", ""))
        if name_re.search(name):
            filtered.append(loc)
    return filtered


def build_location_paths(tree: Sequence[Dict]) -> Dict[str, List[str]]:
    """Map location ids to their breadcrumb path within the tree."""

    paths: Dict[str, List[str]] = {}

    def walk(node: Dict, ancestors: List[str]) -> None:
        if not isinstance(node, dict):
            return
        node_type = (node.get("type") or node.get("nodeType") or "").lower()
        if node_type and node_type != "location":
            return
        name = (node.get("name") or "").strip() or "Unnamed"
        current_path = ancestors + [name]
        loc_id = node.get("id")
        if loc_id:
            paths[loc_id] = current_path
        for child in node.get("children") or []:
            walk(child, current_path)

    for root in tree or []:
        walk(root, [])
    return paths


def location_display_text(name: str) -> str:
    """Normalize user-provided location names."""

    return name.strip() if isinstance(name, str) and name.strip() else "Unnamed"


def split_name_content(name: str) -> Tuple[str, str]:
    """Split a location name into a short title and the remainder."""

    text = location_display_text(name)
    if " " not in text:
        return text, ""
    head, tail = text.split(" ", 1)
    return head, tail.strip()


def extract_categories(description: str) -> List[str]:
    """Extract comma-separated categories from the free-form description."""

    for line in (description or "").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("category:"):
            categories = stripped.split(":", 1)[1]
            return [item.strip() for item in categories.split(",") if item.strip()]
    return []


def wrap_text_lines(text: str, max_chars: int) -> List[str]:
    """Wrap the supplied text into roughly equal-length segments."""

    if not text:
        return []
    max_chars = max(1, max_chars)
    return textwrap.wrap(
        text,
        width=max_chars,
        break_long_words=False,
        drop_whitespace=True,
    )


def shrink_fit(
    text: str,
    max_width_pt: float,
    max_font: float,
    min_font: float,
    font_name: str,
) -> float:
    """Find the largest font size that fits within the given width."""

    size = max_font
    while size >= min_font and stringWidth(text, font_name, size) > max_width_pt:
        size -= 1
    return max(size, min_font)


def build_ui_url(base_ui: str, loc_id: str) -> str:
    """Construct the dashboard URL for a location."""

    return f"{base_ui}/location/{loc_id}" if loc_id else f"{base_ui}/locations"


def collect_label_contents(
    api_manager: HomeboxApiManager,
    base_ui: str,
    name_pattern: Optional[str],
) -> List[LabelContent]:
    """Fetch locations and transform them into label-ready payloads."""

    locations = api_manager.list_locations()
    filtered_locations = _filter_locations_by_name(locations, name_pattern)

    tree = api_manager.get_location_tree()
    path_map = build_location_paths(tree)

    loc_ids = {loc.get("id") for loc in filtered_locations if loc.get("id")}
    detail_map = api_manager.get_location_details(loc_ids)

    base_ui_clean = base_ui.rstrip("/")
    return [
        _to_label_content(loc, detail_map, path_map, base_ui_clean)
        for loc in filtered_locations
    ]


def _to_label_content(
    location: Dict,
    detail_map: Dict[str, Dict],
    path_map: Dict[str, List[str]],
    base_ui: str,
) -> LabelContent:
    """Convert a single location payload into the printable label structure."""

    loc_id = location.get("id") or ""
    detail_payload = detail_map.get(loc_id, {})
    description = (detail_payload.get("description")
                   or location.get("description") or "").strip()
    categories_text = ", ".join(extract_categories(description))

    full_path = path_map.get(loc_id, [])
    trimmed_path = full_path[1:-1] if len(full_path) > 2 else []
    path_text = "->".join(trimmed_path)

    title, content = split_name_content(location.get("name") or "")
    return LabelContent(
        title=title,
        content=content,
        url=build_ui_url(base_ui, loc_id),
        path_text=path_text,
        categories_text=categories_text,
    )


def draw_label(
    canvas_obj: canvas.Canvas,
    geometry: LabelGeometry,
    content: LabelContent,
) -> None:
    """Render a single label into the supplied canvas."""

    column = _render_qr_code(canvas_obj, geometry, content.url)
    _render_label_text(canvas_obj, geometry, content, column)


def _render_qr_code(
    canvas_obj: canvas.Canvas,
    geometry: LabelGeometry,
    url: str,
) -> _TextColumn:
    """Draw the QR code (if any) and report where text may flow."""

    qr_size = geometry.height * 0.7
    qr_bottom = geometry.y + (geometry.height - qr_size) / 2
    if not url or qr_size <= 0.0:
        return _TextColumn(geometry.x, geometry.width)

    buffer = BytesIO()
    qr = qrcode.QRCode(border=0)
    qr.add_data(url)
    qr_img = qr.make_image()
    qr_img.save(buffer, kind="PNG")
    buffer.seek(0)

    canvas_obj.drawImage(
        ImageReader(buffer),
        geometry.x + LABEL_PADDING,
        qr_bottom,
        width=qr_size,
        height=qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )

    column_left = geometry.x + qr_size + 2 * LABEL_PADDING
    column_width = geometry.x + geometry.width - column_left
    return _TextColumn(column_left, column_width)


def _render_label_text(
    canvas_obj: canvas.Canvas,
    geometry: LabelGeometry,
    content: LabelContent,
    column: _TextColumn,
) -> None:
    """Render the textual payload for the label."""
    canvas_obj.saveState()
    canvas_obj.setLineWidth(0.5)
    title_row_y = geometry.y + geometry.height * 3 / 4
    content_row_y = geometry.y + geometry.height / 2
    location_row_y = geometry.y + geometry.height / 4

    canvas_obj.line(column.left, geometry.y, column.left,
                    geometry.y + geometry.height)
    canvas_obj.line(column.left, title_row_y,
                    column.left + column.width, title_row_y)
    canvas_obj.line(column.left, content_row_y,
                    column.left + column.width, content_row_y)
    canvas_obj.line(column.left, location_row_y,
                    column.left + column.width, location_row_y)
    canvas_obj.restoreState()

    center_x = column.left + column.width / 2.0

    context = _TextContext(
        canvas=canvas_obj,
        geometry=geometry,
        column=column,
        center_x=center_x,
    )

    title = location_display_text(content.title)
    canvas_obj.setFont("Helvetica-Bold", TITLE_FONT_SIZE)
    title_y = title_row_y + TEXT_BOTTOM_PAD
    canvas_obj.drawString(column.left + LABEL_PADDING, title_y, title)

    if not content.content:
        return

    content_size = shrink_fit(
        content.content.strip(),
        column.width - LABEL_PADDING,
        max_font=max(TITLE_FONT_SIZE - 2, 22),
        min_font=8,
        font_name="Helvetica-Bold",
    )
    content_y = content_row_y + TEXT_BOTTOM_PAD
    context.canvas.setFont("Helvetica-Bold", content_size)
    context.canvas.drawString(
        context.column.left + LABEL_PADDING, content_y, content.content.strip())


def render_label_pdf(
    output_path: str,
    labels: Sequence[LabelContent],
    skip: int,
) -> None:
    """Render the labels into a PDF using the Avery 5163 layout."""

    canvas_obj = canvas.Canvas(output_path, pagesize=letter)
    template(canvas_obj)

    total = len(labels)
    skip_remaining = max(0, skip)
    index = 0

    while index < total or skip_remaining > 0:
        x0 = MARGIN_LEFT
        y0 = PAGE_H - MARGIN_TOP - LABEL_H
        for row in range(ROWS):
            for col in range(COLS):
                if skip_remaining > 0:
                    skip_remaining -= 1
                    continue
                if index >= total:
                    continue
                geometry = LabelGeometry(
                    x=x0 + col * (LABEL_W + H_GAP),
                    y=y0 - row * LABEL_H,
                    width=LABEL_W,
                    height=LABEL_H,
                )
                draw_label(canvas_obj, geometry, labels[index])
                index += 1
        canvas_obj.showPage()

    canvas_obj.save()


def template(canvas_obj: canvas.Canvas) -> None:
    """Draw the Avery 5163 grid to guide label placement."""

    canvas_obj.setLineWidth(0.5)

    # sanity check to ensure geometry fills page
    total_w = MARGIN_LEFT + COLS * LABEL_W + (COLS - 1) * H_GAP + MARGIN_RIGHT
    total_h = MARGIN_BOTTOM + ROWS * LABEL_H + (ROWS - 1) * V_GAP + MARGIN_TOP
    assert abs(
        total_w - PAGE_W) < 0.01, f"Width mismatch: {total_w} vs {PAGE_W}"
    assert abs(
        total_h - PAGE_H) < 0.01, f"Height mismatch: {total_h} vs {PAGE_H}"

    # draw label rectangles from bottom-left
    for r in range(ROWS):
        for c_idx in range(COLS):
            x = MARGIN_LEFT + c_idx * (LABEL_W + H_GAP) + OFFSET_X
            y = MARGIN_BOTTOM + r * (LABEL_H + V_GAP) + OFFSET_Y
            canvas_obj.rect(x, y, LABEL_W, LABEL_H)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for generating the Homebox label PDF."""

    parser = argparse.ArgumentParser(
        description="Homebox locations -> Avery 2x4 PDF (5163/8163)"
    )
    parser.add_argument("-o", "--output", default="homebox_locations_5163.pdf")
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Number of labels to skip at start of first sheet",
    )
    parser.add_argument(
        "--name-pattern",
        default="box.*",
        help="Case-insensitive regex filter applied to location display names (default: box.*)",
    )
    parser.add_argument(
        "--base",
        default=os.getenv("HOMEBOX_API_URL"),
        help="Homebox base URL (defaults to HOMEBOX_API_URL from the environment/.env).",
    )
    parser.add_argument(
        "--username",
        default=os.getenv("HOMEBOX_USERNAME"),
        help="Homebox username (defaults to HOMEBOX_USERNAME from the environment/.env).",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("HOMEBOX_PASSWORD"),
        help="Homebox password (defaults to HOMEBOX_PASSWORD from the environment/.env).",
    )

    args = parser.parse_args(argv)
    api_manager = HomeboxApiManager(
        base_url=args.base,
        username=args.username,
        password=args.password,
    )

    labels = collect_label_contents(api_manager, args.base, args.name_pattern)
    render_label_pdf(args.output, labels, args.skip)

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":

    load_dotenv()

    main()
