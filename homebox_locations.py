#!/usr/bin/env python3
import argparse, re, sys, textwrap
import requests
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.units import inch
import qrcode
from io import BytesIO
from reportlab.lib.utils import ImageReader

def login(api_base):
    # Homebox accepts form-encoded username/password at /api/v1/users/login
    # Response JSON includes top-level "token".
    # See GitHub discussion for examples. 
    url = f"{api_base}/v1/users/login"
    username = "pfa@pfa.name"
    password = "7#1uL4cB@xrYKr"
    r = requests.post(url, data={
        "username": username,
        "password": password,
        "stayLoggedIn": "true"
    }, headers={"Accept": "application/json"})
    r.raise_for_status()
    data = r.json()
    token = data.get("token")
    if not token:
        raise SystemExit(f"Login failed, response had no token: {data}")
    return token

def fetch_locations(api_base, token):
    url = f"{api_base}/v1/locations"
    r = requests.get(url, headers={"Authorization": f"{token}",
                                   "Accept": "application/json"})
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise SystemExit(f"/locations returned non-array: {type(data)}")
    return data

def shrink_fit(c, text, max_width_pt, max_font=24, min_font=8, font_name="Helvetica-Bold"):
    size = max_font
    while size >= min_font and stringWidth(text, font_name, size) > max_width_pt:
        size -= 1
    size = max(size, min_font)
    return font_name, size

def wrap_lines(text, max_chars):
    # crude wrap for secondary line
    return textwrap.shorten(text, width=max_chars, placeholder="…")

def location_display_text(loc):
    value = loc.get("name")
    if isinstance(value, str):
        value = value.strip()
    return value if value else "Unnamed"

def split_name_content(text):
    text = text.strip()
    if not text:
        return "Unnamed", ""
    if " " not in text:
        return text, ""
    name, content = text.split(" ", 1)
    return name, content.strip()

def location_name_content(loc):
    display = location_display_text(loc)
    return split_name_content(display)

def location_item_count(loc):
    value = loc.get("itemCount")
    if isinstance(value, int):
        return value
    return 0

def draw_label(c, x, y, w, h, name, content, url, add_qr=True):
    pad = 0.12 * inch
    text_left = x + pad
    text_right = x + w - pad
    text_width = max(text_right - text_left, 0)

    # Optional QR occupies full height on the left and shifts text to the right column.
    qr_size = max(h - 2 * pad, 0)
    qr_drawn = False
    if add_qr and url and qr_size > 0:
        buf = BytesIO()
        qrcode.make(url).save(buf, format="PNG")
        buf.seek(0)
        img_x = x + pad
        img_y = y + pad
        c.drawImage(ImageReader(buf), img_x, img_y, width=qr_size, height=qr_size,
                    preserveAspectRatio=True, mask='auto')
        qr_drawn = True
        text_left = img_x + qr_size + pad
        text_width = max(text_right - text_left, 0)

    use_right_column = qr_drawn and text_width > 0
    text_area_width = text_width if use_right_column else max(w - 2 * pad, 0)
    center_x = text_left + text_area_width / 2.0 if use_right_column else x + w / 2.0

    # Title
    title = (name or "Unnamed").strip()
    if not title:
        title = "Unnamed"
    title_width = max(text_area_width, 1)
    fixed_title_size = min(max(int(title_width / 3.6), 16), 36)
    c.setFont("Helvetica-Bold", fixed_title_size)
    title_y = y + h - pad - fixed_title_size
    if use_right_column:
        c.drawString(text_left, title_y, title)
    else:
        c.drawCentredString(center_x, title_y, title)

    # Secondary content just under the title.
    content_text = (content or "").strip()
    if content_text:
        approx_chars = (max(int(title_width / (0.11 * inch)), 1)
                        if use_right_column else 72)
        display_content = wrap_lines(content_text, approx_chars)
        max_content_font = min(fixed_title_size - 4, 24) if fixed_title_size > 14 else fixed_title_size
        max_content_font = max(max_content_font, 10)
        content_font, content_size = shrink_fit(c, display_content, title_width,
                                                max_font=max_content_font, min_font=8,
                                                font_name="Helvetica")
        content_y = max(y + pad, title_y - content_size - 4)
        c.setFont(content_font, content_size)
        if use_right_column:
            c.drawString(text_left, content_y, display_content)
        else:
            c.drawCentredString(center_x, content_y, display_content)

def build_ui_url(base_ui, loc):
    # Prefer numeric id, fallback to uuid
    lid = loc.get("id")
    if lid is None:
        lid = loc.get("uuid") or ""
    return f"{base_ui}/locations/{lid}" if lid != "" else f"{base_ui}/locations"

def main():
    p = argparse.ArgumentParser(description="Homebox locations -> Avery 2x4 PDF (5163/8163)")
    p.add_argument("-o", "--output", default="homebox_locations_5163.pdf")
    p.add_argument("--no-qr", action="store_true", help="Disable QR codes on labels")
    p.add_argument("--skip", type=int, default=0,
                   help="Number of labels to skip at start of first sheet")
    # Layout overrides, if you need alignment tweaks
    p.add_argument("--left-margin-in", type=float, default=0.15625)
    p.add_argument("--right-margin-in", type=float, default=0.15625)
    p.add_argument("--top-margin-in", type=float, default=0.5)
    p.add_argument("--bottom-margin-in", type=float, default=0.5)
    p.add_argument("--col-gap-in", type=float, default=0.1875)
    p.add_argument("--name-pattern", default="box.*",
                   help="Case-insensitive regex filter applied to location display names (default: box.*)")
    args = p.parse_args()

    base = "https://homebox.home.pfa.name"
    api_base = f"{base}/api"

    token = login(api_base)
    locs = fetch_locations(api_base, token)
    pattern = args.name_pattern
    if pattern:
        try:
            name_re = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise SystemExit(f"Invalid --name-pattern regex '{pattern}': {e}")
        locs = [loc for loc in locs if name_re.search(location_display_text(loc))]
    locs = [loc for loc in locs if location_item_count(loc) > 0]

    # Page and label geometry per 5163/8163
    page_w, page_h = letter  # 8.5 x 11 in
    label_w = 4.0 * inch
    label_h = 2.0 * inch
    cols, rows = 2, 5

    lm = args.left_margin_in * inch
    rm = args.right_margin_in * inch
    tm = args.top_margin_in * inch
    bm = args.bottom_margin_in * inch
    gap = args.col_gap_in * inch

    c = canvas.Canvas(args.output, pagesize=letter)

    idx = 0
    expanded_locs = []
    for loc in locs:
        expanded_locs.extend([loc, loc])

    total = len(expanded_locs)
    i = 0

    # pre-skip labels on first sheet if using a partial sheet
    skip = max(0, args.skip)
    # iterate pages until all labels placed
    while i < total or skip > 0:
        # draw grid of labels
        x0 = lm
        y0 = page_h - tm - label_h  # top row origin

        for r in range(rows):
            for col in range(cols):
                if skip > 0:
                    skip -= 1
                elif i < total:
                    loc = expanded_locs[i]
                    name, content = location_name_content(loc)
                    url = build_ui_url(base, loc)
                    x = x0 + col * (label_w + gap)
                    y = y0 - r * label_h  # no vertical gap for 5163
                    draw_label(c, x, y, label_w, label_h, name, content, url, add_qr=not args.no_qr)
                    i += 1
                # else leave blank
            # next row
        c.showPage()

    c.save()
    print(f"Wrote {args.output}")

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        sys.exit(f"HTTP error: {e.response.status_code} {e.response.text[:2000]}")
    except Exception as e:
        sys.exit(str(e))
