#!/usr/bin/env python3
"""Generate Avery 5163 label sheets from Homebox location data."""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, List, Optional, Sequence, Tuple

from dotenv import load_dotenv

import qrcode
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from homebox_api import HomeboxApiManager
from fonts import FontConfig, FontSpec, build_font_config

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

TEXT_BOTTOM_PAD = 0.06 * inch


@dataclass(frozen=True)
class LabelContent:
    """Textual payload to render into a label."""

    title: str
    content: str
    url: str
    path_text: str = ""
    categories_text: str = ""


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


def wrap_text_to_width(
    text: str,
    font_name: str,
    font_size: float,
    max_width_pt: float,
) -> List[str]:
    """Wrap text to fit within the specified width using font metrics."""

    if not text or max_width_pt <= 0.0:
        return []

    words = text.split()
    if not words:
        return []

    lines: List[str] = []
    current: List[str] = []
    for word in words:
        tentative = " ".join(current + [word]) if current else word
        if stringWidth(tentative, font_name, font_size) <= max_width_pt or not current:
            current.append(word)
            continue
        lines.append(" ".join(current))
        current = [word]

    if current:
        lines.append(" ".join(current))
    return lines


def shrink_fit(
    text: str,
    max_width_pt: float,
    max_font: float,
    min_font: float,
    font_name: str,
    step: float = 1.0,
) -> float:
    """Find the largest font size that fits within the given width."""

    size = max_font
    step = max(step, 0.25)
    while size >= min_font and stringWidth(text, font_name, size) > max_width_pt:
        size -= step
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
    content: LabelContent,
    fonts: FontConfig,
) -> None:
    """Render a single label into the supplied canvas."""

    _render_qr_code(canvas_obj, content.url)
    _render_label_text(canvas_obj, content, fonts)


def _render_qr_code(
    canvas_obj: canvas.Canvas,
    url: str,
):
    """Draw the QR code (if any) and report where text may flow."""

    qr_size = LABEL_H * 0.75 - 2 * LABEL_PADDING
    qr_bottom = LABEL_PADDING

    buffer = BytesIO()
    qr = qrcode.QRCode(border=0)
    qr.add_data(url)
    qr_img = qr.make_image()
    qr_img.save(buffer, kind="PNG")
    buffer.seek(0)

    canvas_obj.drawImage(
        ImageReader(buffer),
        LABEL_PADDING,
        qr_bottom,
        width=qr_size,
        height=qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )


def _render_label_text(
    canvas_obj: canvas.Canvas,
    content: LabelContent,
    fonts: FontConfig,
) -> None:
    """Render the textual payload for the label."""
    left = LABEL_H * 0.75 - 2 * LABEL_PADDING
    canvas_obj.saveState()
    canvas_obj.setLineWidth(0.5)

    title_row_y = LABEL_H * 3 / 4
    content_row_y = LABEL_H / 2
    info_row_y = LABEL_H / 4

    canvas_obj.line(left, 0, left, title_row_y)
    canvas_obj.line(0, title_row_y, LABEL_W, title_row_y)
    canvas_obj.line(left, content_row_y, LABEL_W, content_row_y)
    canvas_obj.line(left, info_row_y, LABEL_W, info_row_y)
    canvas_obj.restoreState()

    label_x = left / 2

    # Render section headings in the left column if available.
    canvas_obj.setFont(fonts.label.font_name, fonts.label.size)
    heading_positions = [
        ("Title", (LABEL_H + title_row_y) / 2.0),
        ("Content", (title_row_y + content_row_y) / 2.0),
        ("Info", (content_row_y) / 2.0),
    ]
    for text, y in heading_positions:
        canvas_obj.drawCentredString(label_x, y, text)

    text_start_x = max(left + LABEL_PADDING, LABEL_PADDING)
    text_max_width = max(LABEL_W - LABEL_PADDING - text_start_x, 0.0)

    title = location_display_text(content.title)
    title_max = fonts.title.size
    title_min = max(title_max * 0.5, 8.0)
    title_size = shrink_fit(
        title,
        text_max_width,
        max_font=title_max,
        min_font=title_min,
        font_name=fonts.title.font_name,
        step=0.5,
    )
    title_y = title_row_y + TEXT_BOTTOM_PAD
    canvas_obj.setFont(fonts.title.font_name, title_size)
    canvas_obj.drawString(text_start_x, title_y, title)

    # Subtitle / content row.
    body_text = content.content.strip()
    if body_text:
        body_max = fonts.content.size
        body_min = max(body_max * 0.5, 6.0)
        body_size = shrink_fit(
            body_text,
            text_max_width,
            max_font=body_max,
            min_font=body_min,
            font_name=fonts.content.font_name,
            step=0.5,
        )
        body_y = content_row_y + TEXT_BOTTOM_PAD
        canvas_obj.setFont(fonts.content.font_name, body_size)
        canvas_obj.drawString(text_start_x, body_y, body_text)

    # Detail lines (path, categories, URL) using the label font.
    info_lines: List[str] = []

    def append_info(prefix: str, value: str) -> None:
        if not value:
            return
        text = f"{prefix}{value.strip()}"
        info_lines.extend(
            wrap_text_to_width(
                text=text,
                font_name=fonts.label.font_name,
                font_size=fonts.label.size,
                max_width_pt=text_max_width,
            )
        )

    append_info("Path: ", content.path_text)
    append_info("Tags: ", content.categories_text)
    append_info("URL: ", content.url)

    if info_lines:
        info_y = info_row_y - TEXT_BOTTOM_PAD - fonts.label.size
        canvas_obj.setFont(fonts.label.font_name, fonts.label.size)
        for line in info_lines:
            if info_y < fonts.label.size:
                break
            canvas_obj.drawString(text_start_x, info_y, line)
            info_y -= fonts.label.size + (TEXT_BOTTOM_PAD / 2.0)


def render_label_pdf(
    output_path: str,
    labels: Sequence[LabelContent],
    skip: int,
    fonts: FontConfig,
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
                canvas_obj.saveState()
                canvas_obj.translate(
                    x0 + col * (LABEL_W + H_GAP), y0 - row * LABEL_H)

                draw_label(canvas_obj, labels[index], fonts)
                canvas_obj.restoreState()
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
    parser.add_argument(
        "--font-family",
        default="Inter",
        help="Variable font family to download and use (default: Inter).",
    )
    parser.add_argument(
        "--font-url",
        help="Override download URL for the variable font file.",
    )
    parser.add_argument(
        "--font-title-weight",
        type=float,
        default=700.0,
        help="Font weight for the title text (default: 700).",
    )
    parser.add_argument(
        "--font-title-size",
        type=float,
        default=22.0,
        help="Font size for the title text in points (default: 22).",
    )
    parser.add_argument(
        "--font-content-weight",
        type=float,
        default=600.0,
        help="Font weight for the content/subtitle text (default: 600).",
    )
    parser.add_argument(
        "--font-content-size",
        type=float,
        default=20.0,
        help="Font size for the content/subtitle text in points (default: 20).",
    )
    parser.add_argument(
        "--font-label-weight",
        type=float,
        default=500.0,
        help="Font weight for supplemental label text (default: 500).",
    )
    parser.add_argument(
        "--font-label-size",
        type=float,
        default=12.0,
        help="Font size for supplemental label text in points (default: 12).",
    )
    args = parser.parse_args(argv)

    for value, flag in [
        (args.font_title_size, "--font-title-size"),
        (args.font_content_size, "--font-content-size"),
        (args.font_label_size, "--font-label-size"),
    ]:
        if value <= 0:
            raise SystemExit(f"{flag} must be greater than zero.")

    try:
        fonts = build_font_config(
            family=args.font_family,
            title_spec=FontSpec(weight=args.font_title_weight,
                                size=args.font_title_size),
            content_spec=FontSpec(
                weight=args.font_content_weight, size=args.font_content_size),
            label_spec=FontSpec(weight=args.font_label_weight,
                                size=args.font_label_size),
            url=args.font_url,
        )
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

    api_manager = HomeboxApiManager(
        base_url=args.base,
        username=args.username,
        password=args.password,
    )

    labels = collect_label_contents(api_manager, args.base, args.name_pattern)
    render_label_pdf(args.output, labels, args.skip, fonts)

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":

    load_dotenv()

    main()
