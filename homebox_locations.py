#!/usr/bin/env python3
"""Generate Avery 5163 label sheets from Homebox location data."""

import argparse
import re
import sys
import textwrap
from io import BytesIO
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import qrcode
import requests
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


DEFAULT_USERNAME = "pfa@pfa.name"
DEFAULT_PASSWORD = "7#1uL4cB@xrYKr"
DEFAULT_BASE = "https://homebox.home.pfa.name"
DEFAULT_TIMEOUT = 30


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


@dataclass(frozen=True)
class LabelContent:
    """Textual payload to render into a label."""

    title: str
    subtitle: str
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
    align_left: bool


@dataclass(frozen=True)
class _TextContext:
    """Shared state for rendering text blocks within a label."""

    canvas: canvas.Canvas
    geometry: LabelGeometry
    column: _TextColumn
    center_x: float
    text_area_width: float

def login(api_base: str, username: str, password: str) -> str:
    """Authenticate with the Homebox API and return a session token."""

    response = requests.post(
        f"{api_base}/v1/users/login",
        data={"username": username, "password": password, "stayLoggedIn": "true"},
        headers={"Accept": "application/json"},
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    token = response.json().get("token")
    if not token:
        raise SystemExit("Login succeeded but did not return a token.")
    return token


def auth_headers(token: str) -> Dict[str, str]:
    """Build the authorization header payload."""

    return {"Authorization": token, "Accept": "application/json"}


def fetch_locations(api_base: str, token: str) -> List[Dict]:
    """Fetch the flat list of available locations."""

    response = requests.get(
        f"{api_base}/v1/locations", headers=auth_headers(token), timeout=DEFAULT_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise SystemExit(f"/v1/locations returned unexpected payload: {type(data)}")
    return data


def fetch_location_tree(api_base: str, token: str) -> List[Dict]:
    """Retrieve the hierarchical location tree."""

    response = requests.get(
        f"{api_base}/v1/locations/tree",
        headers=auth_headers(token),
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise SystemExit(f"/v1/locations/tree returned unexpected payload: {type(data)}")
    return data


def fetch_location_detail(api_base: str, token: str, location_id: str) -> Dict:
    """Fetch the API payload for a single location."""

    response = requests.get(
        f"{api_base}/v1/locations/{location_id}",
        headers=auth_headers(token),
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    detail = response.json()
    if not isinstance(detail, dict):
        raise SystemExit(f"/v1/locations/{location_id} returned unexpected payload")
    return detail


def fetch_location_details(api_base: str, token: str, loc_ids: Iterable[str]) -> Dict[str, Dict]:
    """Fetch details for all requested location ids."""

    details: Dict[str, Dict] = {}
    for loc_id in loc_ids:
        if not loc_id:
            continue
        details[loc_id] = fetch_location_detail(api_base, token, loc_id)
    return details


def _filter_locations_by_name(locations: Sequence[Dict], pattern: Optional[str]) -> List[Dict]:
    """Apply the name regex filter declared by the user."""

    if not pattern:
        return list(locations)

    try:
        name_re = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise SystemExit(f"Invalid --name-pattern regex '{pattern}': {exc}") from exc

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
    api_base: str,
    base_ui: str,
    token: str,
    name_pattern: Optional[str],
) -> List[LabelContent]:
    """Fetch locations and transform them into label-ready payloads."""

    locations = fetch_locations(api_base, token)
    filtered_locations = _filter_locations_by_name(locations, name_pattern)

    tree = fetch_location_tree(api_base, token)
    path_map = build_location_paths(tree)

    loc_ids = {loc.get("id") for loc in filtered_locations if loc.get("id")}
    detail_map = fetch_location_details(api_base, token, loc_ids)

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
    description = (detail_payload.get("description") or location.get("description") or "").strip()
    categories_text = ", ".join(extract_categories(description))

    full_path = path_map.get(loc_id, [])
    trimmed_path = full_path[1:-1] if len(full_path) > 2 else []
    path_text = "->".join(trimmed_path)

    title, content = split_name_content(location.get("name") or "")
    return LabelContent(
        title=title,
        subtitle=content,
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

    column = _reserve_text_column(canvas_obj, geometry, content.url)
    _render_label_text(canvas_obj, geometry, content, column)


def _reserve_text_column(
    canvas_obj: canvas.Canvas,
    geometry: LabelGeometry,
    url: str,
) -> _TextColumn:
    """Draw the QR code (if any) and report where text may flow."""

    text_left = geometry.x + LABEL_PADDING
    text_right = geometry.x + geometry.width - LABEL_PADDING
    text_width = max(text_right - text_left, 0.0)

    qr_size = max(geometry.height - 2 * LABEL_PADDING, 0.0)
    if not url or qr_size <= 0.0:
        return _TextColumn(text_left, text_width, align_left=False)

    buffer = BytesIO()
    qr = qrcode.QRCode()
    qr.add_data(url)
    qr_img = qr.make_image()
    qr_img.save(buffer, format="PNG")
    buffer.seek(0)

    canvas_obj.drawImage(
        ImageReader(buffer),
        geometry.x,
        geometry.y,
        width=qr_size,
        height=qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )

    border_pt = qr.border * qr.box_size
    line_x = geometry.x + qr_size - 2 * border_pt
    canvas_obj.saveState()
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(line_x, geometry.y + border_pt, line_x, geometry.y + qr_size - border_pt)
    canvas_obj.restoreState()

    column_left = line_x + border_pt
    column_width = max(text_right - column_left, 0.0)
    return _TextColumn(column_left, column_width, align_left=True)


def _render_label_text(
    canvas_obj: canvas.Canvas,
    geometry: LabelGeometry,
    content: LabelContent,
    column: _TextColumn,
) -> None:
    """Render the textual payload for the label."""

    text_area_width = (
        column.width if column.align_left else max(geometry.width - 2 * LABEL_PADDING, 0.0)
    )
    center_x = (
        column.left + text_area_width / 2.0
        if column.align_left
        else geometry.x + geometry.width / 2.0
    )
    context = _TextContext(
        canvas=canvas_obj,
        geometry=geometry,
        column=column,
        center_x=center_x,
        text_area_width=text_area_width,
    )

    title = location_display_text(content.title)
    title_size = shrink_fit(
        title,
        text_area_width,
        max_font=28,
        min_font=12,
        font_name="Helvetica-Bold",
    )
    canvas_obj.setFont("Helvetica-Bold", title_size)
    title_y = geometry.y + geometry.height - LABEL_PADDING - title_size
    if column.align_left:
        canvas_obj.drawString(column.left, title_y, title)
    else:
        canvas_obj.drawCentredString(center_x, title_y, title)

    subtitle_text = content.subtitle.strip()
    subtitle_y, subtitle_size = _draw_subtitle(context, title_y, title_size, subtitle_text)
    detail_lines = [value for value in (content.path_text, content.categories_text) if value]
    _draw_detail_lines(context, subtitle_y, subtitle_size, detail_lines)


def _draw_subtitle(
    context: _TextContext,
    title_y: float,
    title_size: float,
    subtitle_text: str,
) -> Tuple[float, float]:
    """Draw the optional subtitle block and return the next Y offset."""

    if not subtitle_text:
        fallback_size = max(title_size - 4, 10)
        fallback_y = title_y - fallback_size - 6
        return fallback_y, fallback_size

    subtitle_size = shrink_fit(
        subtitle_text,
        context.text_area_width,
        max_font=max(title_size - 2, 22),
        min_font=8,
        font_name="Helvetica-Bold",
    )
    subtitle_y = title_y - subtitle_size - 6
    context.canvas.setFont("Helvetica-Bold", subtitle_size)
    if context.column.align_left:
        context.canvas.drawString(context.column.left, subtitle_y, subtitle_text)
    else:
        context.canvas.drawCentredString(context.center_x, subtitle_y, subtitle_text)
    return subtitle_y, subtitle_size


def _draw_detail_lines(
    context: _TextContext,
    start_y: float,
    base_font_size: float,
    detail_lines: Sequence[str],
) -> None:
    """Render any extra detail lines within the remaining space."""

    if not detail_lines:
        return

    approx_chars = max(int(context.text_area_width / (0.115 * inch)), 1)
    current_y = start_y
    for raw_line in detail_lines:
        for segment in wrap_text_lines(raw_line, approx_chars):
            detail_size = shrink_fit(
                segment,
                context.text_area_width,
                max_font=max(base_font_size - 2, 12),
                min_font=6,
                font_name="Helvetica-Bold",
            )
            current_y -= detail_size + 3
            current_y = max(current_y, context.geometry.y + LABEL_PADDING)
            context.canvas.setFont("Helvetica-Bold", detail_size)
            if context.column.align_left:
                context.canvas.drawString(context.column.left, current_y, segment)
            else:
                context.canvas.drawCentredString(context.center_x, current_y, segment)


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
    assert abs(total_w - PAGE_W) < 0.01, f"Width mismatch: {total_w} vs {PAGE_W}"
    assert abs(total_h - PAGE_H) < 0.01, f"Height mismatch: {total_h} vs {PAGE_H}"

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
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args(argv)

    api_base = f"{args.base.rstrip('/')}/api"
    token = login(api_base, args.username, args.password)

    labels = collect_label_contents(api_base, args.base, token, args.name_pattern)
    render_label_pdf(args.output, labels, args.skip)

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.HTTPError as http_err:
        sys.exit(f"HTTP error: {http_err.response.status_code} {http_err.response.text[:2000]}")
    except requests.RequestException as req_err:  # pragma: no cover - top-level safeguard
        sys.exit(str(req_err))
