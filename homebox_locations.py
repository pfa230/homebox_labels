#!/usr/bin/env python3
import argparse
import re
import sys
import shutil
import textwrap
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import qrcode

from qrcode import constants, exceptions, util
from qrcode.image.base import BaseImage
from qrcode.image.pure import PyPNGImage
from qrcode.image.pil import PilImage
import requests
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from reportlab.pdfgen import canvas

try:
    from fontTools.ttLib import TTFont as TTFontReader
    from fontTools.varLib import instancer as var_instancer
except ImportError:  # pragma: no cover - optional enhancement
    TTFontReader = None
    var_instancer = None

DEFAULT_USERNAME = "pfa@pfa.name"
DEFAULT_PASSWORD = "7#1uL4cB@xrYKr"
DEFAULT_BASE = "https://homebox.home.pfa.name"
DEFAULT_TIMEOUT = 30


# --- Template geometry (in inches) ---
PAGE_W, PAGE_H = letter  # 8.5 x 11 in in points
inch_pt = inch

label_w = 4.00 * inch_pt
label_h = 2.00 * inch_pt

cols = 2
rows = 5

# Margins and gaps chosen to exactly fill 8.5" width and 11" height
# Adjust if your printer shifts: set offset_x, offset_y below.
margin_left  = 0.17 * inch_pt
margin_right = 0.17 * inch_pt
margin_top   = 0.50 * inch_pt
margin_bottom= 0.50 * inch_pt

h_gap = 0.16 * inch_pt   # between columns
v_gap = 0.00 * inch_pt   # between rows

# Optional printer compensation offsets (positive moves right/up)
offset_x = 0.00 * inch_pt
offset_y = 0.00 * inch_pt

def login(api_base: str, username: str, password: str) -> str:
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
    return {"Authorization": token, "Accept": "application/json"}


def fetch_locations(api_base: str, token: str) -> List[Dict]:
    response = requests.get(
        f"{api_base}/v1/locations", headers=auth_headers(token), timeout=DEFAULT_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise SystemExit(f"/v1/locations returned unexpected payload: {type(data)}")
    return data


def fetch_location_tree(api_base: str, token: str) -> List[Dict]:
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
    details: Dict[str, Dict] = {}
    for loc_id in loc_ids:
        if not loc_id:
            continue
        details[loc_id] = fetch_location_detail(api_base, token, loc_id)
    return details


def build_location_paths(tree: Sequence[Dict]) -> Dict[str, List[str]]:
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
    return name.strip() if isinstance(name, str) and name.strip() else "Unnamed"


def split_name_content(name: str) -> (str, str):
    text = location_display_text(name)
    if " " not in text:
        return text, ""
    head, tail = text.split(" ", 1)
    return head, tail.strip()


def extract_categories(description: str) -> List[str]:
    for line in (description or "").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("category:"):
            categories = stripped.split(":", 1)[1]
            return [item.strip() for item in categories.split(",") if item.strip()]
    return []


def wrap_text_lines(text: str, max_chars: int) -> List[str]:
    if not text:
        return []
    max_chars = max(1, max_chars)
    return textwrap.wrap(
        text,
        width=max_chars,
        break_long_words=False,
        drop_whitespace=True,
    )


def shrink_fit(text: str, max_width_pt: float, max_font: float, min_font: float, font_name: str) -> float:
    size = max_font
    while size >= min_font and stringWidth(text, font_name, size) > max_width_pt:
        size -= 1
    return max(size, min_font)


def build_ui_url(base_ui: str, loc_id: str) -> str:
    return f"{base_ui}/location/{loc_id}" if loc_id else f"{base_ui}/locations"


def draw_label(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    name: str,
    content: str,
    url: str,
    path_text: str = "",
    categories_text: str = ""
) -> None:
    pad = 0.12 * inch
    text_left = x + pad
    text_right = x + w - pad
    text_width = max(text_right - text_left, 0)

    qr_size = max(h - 2 * pad, 0)
    qr_drawn = False
    if url and qr_size > 0:
        # qr_img = qrcode.make(url)
        # pixel_width = qr_img.size[0]
        
        buf = BytesIO()
        qr = qrcode.QRCode()
        qr.add_data(url)
        qr_img = qr.make_image()
        qr_img.save(buf, format="PNG")
        
        buf.seek(0)
        img_x = x# + pad
        img_y = y #+ pad
        c.drawImage(
            ImageReader(buf),
            img_x,
            img_y,
            width=qr_size,
            height=qr_size,
            preserveAspectRatio=True,
            mask="auto",
        )
        # Divider line between QR code and text column
        # scale = qr_size / pixel_width
        border_pt = qr.border * qr.box_size 
        line_x = x + qr_size - 2 * border_pt
        c.saveState()
        c.setLineWidth(0.5)
        c.line(line_x, img_y + border_pt, line_x, img_y + qr_size - border_pt)
        c.restoreState()
        qr_drawn = True
        text_left = line_x + border_pt
        text_width = max(text_right - text_left, 0)

    use_right_column = qr_drawn and text_width > 0
    text_area_width = text_width if use_right_column else max(w - 2 * pad, 0)
    center_x = text_left + text_area_width / 2.0 if use_right_column else x + w / 2.0

    title = location_display_text(name)
    title_size = shrink_fit(title, text_area_width, max_font=28, min_font=12, font_name="Helvetica-Bold")
    c.setFont("Helvetica-Bold", title_size)
    title_y = y + h - pad - title_size
    if use_right_column:
        c.drawString(text_left, title_y, title)
    else:
        c.drawCentredString(center_x, title_y, title)

    content_text = content.strip()
    if content_text:
        content_size = shrink_fit(
            content_text,
            text_area_width,
            max_font=max(title_size - 2, 22),
            min_font=8,
            font_name="Helvetica-Bold",
        )
        content_y = title_y - content_size - 6
        c.setFont("Helvetica-Bold", content_size)
        if use_right_column:
            c.drawString(text_left, content_y, content_text)
        else:
            c.drawCentredString(center_x, content_y, content_text)
    else:
        content_size = max(title_size - 4, 10)
        content_y = title_y - content_size - 6

    extras: List[str] = []
    if path_text:
        extras.append(path_text)
    if categories_text:
        extras.append(categories_text)

    approx_chars = max(int(text_area_width / (0.115 * inch)), 1)
    current_y = content_y
    for raw_line in extras:
        for segment in wrap_text_lines(raw_line, approx_chars):
            extra_size = shrink_fit(
                segment,
                text_area_width,
                max_font=max(content_size - 2, 12),
                min_font=6,
                font_name="Helvetica-Bold",
            )
            current_y -= extra_size + 3
            if current_y < y + pad:
                current_y = y + pad
            c.setFont("Helvetica-Bold", extra_size)
            if use_right_column:
                c.drawString(text_left, current_y, segment)
            else:
                c.drawCentredString(center_x, current_y, segment)

def template(c):
    c.setLineWidth(0.5)

    # sanity check to ensure geometry fills page
    total_w = margin_left + cols*label_w + (cols-1)*h_gap + margin_right
    total_h = margin_bottom + rows*label_h + (rows-1)*v_gap + margin_top
    assert abs(total_w - PAGE_W) < 0.01, f"Width mismatch: {total_w} vs {PAGE_W}"
    assert abs(total_h - PAGE_H) < 0.01, f"Height mismatch: {total_h} vs {PAGE_H}"

    # draw label rectangles from bottom-left
    for r in range(rows):
        for c_idx in range(cols):
            x = margin_left + c_idx*(label_w + h_gap) + offset_x
            y = margin_bottom + r*(label_h + v_gap) + offset_y
            c.rect(x, y, label_w, label_h)

    
def fetch_data():
    pass

def main(argv: Optional[Sequence[str]] = None) -> int:
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

    locations = fetch_locations(api_base, token)
    pattern = args.name_pattern
    if pattern:
        try:
            name_re = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise SystemExit(f"Invalid --name-pattern regex '{pattern}': {exc}") from exc
        locations = [loc for loc in locations if name_re.search(location_display_text(loc.get("name", "")))]

    tree = fetch_location_tree(api_base, token)
    path_map = build_location_paths(tree)
    detail_map = fetch_location_details(api_base, token, {loc.get("id") for loc in locations})

    label_items = []
    for loc in locations:
        loc_id = loc.get("id")
        name = loc.get("name") or ""
        detail = detail_map.get(loc_id, {})
        description = (detail.get("description") or loc.get("description") or "").strip()
        categories = extract_categories(description)
        categories_text = ", ".join(categories)

        full_path = path_map.get(loc_id, [])
        trimmed_path = full_path[1:-1] if len(full_path) > 2 else []
        path_text = "->".join(trimmed_path)

        title, content = split_name_content(name)
        label_items.append(
            {
                "title": title,
                "content": content,
                "url": build_ui_url(args.base.rstrip("/"), loc_id),
                "path": path_text,
                "categories": categories_text,
            }
        )

    page_w, page_h = letter
    label_w = 4.0 * inch
    label_h = 2.0 * inch
    cols, rows = 2, 5

    total = len(label_items)
    skip = max(0, args.skip)
    i = 0

    c = canvas.Canvas(args.output, pagesize=letter)
    template(c)
    while i < total or skip > 0:
        x0 = margin_left
        y0 = page_h - margin_top - label_h
        for row in range(rows):
            for col in range(cols):
                if skip > 0:
                    skip -= 1
                    continue
                if i >= total:
                    continue
                item = label_items[i]
                x = x0 + col * (label_w + h_gap)
                y = y0 - row * label_h
                draw_label(
                    c,
                    x,
                    y,
                    label_w,
                    label_h,
                    name=item["title"],
                    content=item["content"],
                    url=item["url"],
                    path_text=item["path"],
                    categories_text=item["categories"],                  
                )
                i += 1
        c.showPage()

    c.save()
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.HTTPError as http_err:
        sys.exit(f"HTTP error: {http_err.response.status_code} {http_err.response.text[:2000]}")
    except Exception as exc:  # pragma: no cover - top-level safeguard
        sys.exit(str(exc))
