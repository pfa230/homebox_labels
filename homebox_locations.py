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
import requests
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
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

FONT_CACHE_DIR = Path(__file__).resolve().parent / ".font_cache"
FONT_SEARCH_PATHS = [
    Path.home() / "Library" / "Fonts",
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
]

TITLE_FONT_NAME = "Inter-SemiBold-600"
CONTENT_FONT_NAME = "Inter-Medium-500"
EXTRA_FONT_NAME = "Inter-Medium-500"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def register_font(font_name: str, font_path: Path) -> None:
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))


def enable_numeric_features(font_path: Path, features: Sequence[str] = ("tnum", "zero")) -> None:
    if TTFontReader is None:
        return
    try:
        font = TTFontReader(str(font_path))
    except Exception:  # pragma: no cover - defensive
        return
    changed = False
    if "GSUB" in font:
        gsub_table = font["GSUB"].table
        feature_list = getattr(gsub_table, "FeatureList", None)
        script_list = getattr(gsub_table, "ScriptList", None)
        if feature_list and script_list and feature_list.FeatureRecord:
            feature_index_map = {
                record.FeatureTag: idx for idx, record in enumerate(feature_list.FeatureRecord)
            }
            desired = [tag for tag in features if tag in feature_index_map]
            if desired:
                for script_record in script_list.ScriptRecord or []:
                    lang_systems: List = []
                    default_lang = getattr(script_record.Script, "DefaultLangSys", None)
                    if default_lang:
                        lang_systems.append(default_lang)
                    for lang_record in getattr(script_record.Script, "LangSysRecord", []) or []:
                        if lang_record.LangSys:
                            lang_systems.append(lang_record.LangSys)
                    for lang_sys in lang_systems:
                        indices = list(getattr(lang_sys, "FeatureIndex", []))
                        present = set(indices)
                        updated = False
                        for tag in desired:
                            idx = feature_index_map[tag]
                            if idx not in present:
                                indices.append(idx)
                                present.add(idx)
                                updated = True
                        if updated:
                            lang_sys.FeatureIndex = indices
                            lang_sys.FeatureCount = len(indices)
                            changed = True
    if changed:
        font.save(str(font_path))
    font.close()


def instantiate_variable_font(source: Path, dest: Path, axes: Dict[str, float]) -> Path:
    if dest.exists():
        return dest
    if TTFontReader is None or var_instancer is None:
        raise SystemExit(
            "fontTools with varLib is required to instantiate variable fonts without downloads."
        )
    font = TTFontReader(str(source))
    var_instancer.instantiateVariableFont(font, axes, inplace=True)
    for table in ("fvar", "gvar", "avar", "HVAR", "MVAR", "STAT", "meta"):
        if table in font:
            try:
                del font[table]
            except KeyError:
                pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(dest))
    font.close()
    return dest


def locate_font_file(candidates: Sequence[str]) -> Optional[Path]:
    for directory in FONT_SEARCH_PATHS:
        for candidate in candidates:
            candidate_path = directory / candidate
            if candidate_path.exists():
                return candidate_path
    return None


def register_inter_fonts() -> None:
    ensure_dir(FONT_CACHE_DIR)
    variable_source = locate_font_file(
        [
            "InterVariable.ttf",
            "InterVariable-Regular.ttf",
            "InterVariable.otf",
            "InterVariable (TrueType).ttf",
        ]
    )
    if not variable_source:
        raise SystemExit(
            "InterVariable.ttf not found. Install the Inter variable font locally."
        )
    variable_path = FONT_CACHE_DIR / variable_source.name
    if not variable_path.exists():
        shutil.copy2(variable_source, variable_path)
    title_path = instantiate_variable_font(
        variable_path,
        FONT_CACHE_DIR / "Inter-SemiBold-600.ttf",
        {"wght": 600.0, "opsz": 14.0},
    )
    content_path = instantiate_variable_font(
        variable_path,
        FONT_CACHE_DIR / "Inter-Medium-500.ttf",
        {"wght": 500.0, "opsz": 14.0},
    )

    for path in (title_path, content_path):
        enable_numeric_features(path, ("tnum", "zero"))
    register_font(TITLE_FONT_NAME, title_path)
    register_font(CONTENT_FONT_NAME, content_path)
    if EXTRA_FONT_NAME != CONTENT_FONT_NAME:
        register_font(EXTRA_FONT_NAME, content_path)


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
    categories_text: str = "",
    add_qr: bool = True,
) -> None:
    pad = 0.12 * inch
    text_left = x + pad
    text_right = x + w - pad
    text_width = max(text_right - text_left, 0)

    qr_size = max(h - 2 * pad, 0)
    qr_drawn = False
    if add_qr and url and qr_size > 0:
        buf = BytesIO()
        qrcode.make(url).save(buf, format="PNG")
        buf.seek(0)
        img_x = x + pad
        img_y = y + pad
        c.drawImage(
            ImageReader(buf),
            img_x,
            img_y,
            width=qr_size,
            height=qr_size,
            preserveAspectRatio=True,
            mask="auto",
        )
        qr_drawn = True
        text_left = img_x + qr_size + pad
        text_width = max(text_right - text_left, 0)

    use_right_column = qr_drawn and text_width > 0
    text_area_width = text_width if use_right_column else max(w - 2 * pad, 0)
    center_x = text_left + text_area_width / 2.0 if use_right_column else x + w / 2.0

    title = location_display_text(name)
    title_size = shrink_fit(title, text_area_width, max_font=28, min_font=12, font_name=TITLE_FONT_NAME)
    c.setFont(TITLE_FONT_NAME, title_size)
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
            font_name=CONTENT_FONT_NAME,
        )
        content_y = title_y - content_size - 6
        c.setFont(CONTENT_FONT_NAME, content_size)
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
                font_name=EXTRA_FONT_NAME,
            )
            current_y -= extra_size + 3
            if current_y < y + pad:
                current_y = y + pad
            c.setFont(EXTRA_FONT_NAME, extra_size)
            if use_right_column:
                c.drawString(text_left, current_y, segment)
            else:
                c.drawCentredString(center_x, current_y, segment)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Homebox locations -> Avery 2x4 PDF (5163/8163)"
    )
    parser.add_argument("-o", "--output", default="homebox_locations_5163.pdf")
    parser.add_argument("--no-qr", action="store_true", help="Disable QR codes on labels")
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Number of labels to skip at start of first sheet",
    )
    parser.add_argument("--left-margin-in", type=float, default=0.15625)
    parser.add_argument("--right-margin-in", type=float, default=0.15625)
    parser.add_argument("--top-margin-in", type=float, default=0.5)
    parser.add_argument("--bottom-margin-in", type=float, default=0.5)
    parser.add_argument("--col-gap-in", type=float, default=0.1875)
    parser.add_argument(
        "--name-pattern",
        default="box.*",
        help="Case-insensitive regex filter applied to location display names (default: box.*)",
    )
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args(argv)

    register_inter_fonts()

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

    left_margin = args.left_margin_in * inch
    right_margin = args.right_margin_in * inch
    top_margin = args.top_margin_in * inch
    bottom_margin = args.bottom_margin_in * inch
    col_gap = args.col_gap_in * inch

    total = len(label_items)
    skip = max(0, args.skip)
    i = 0

    c = canvas.Canvas(args.output, pagesize=letter)
    while i < total or skip > 0:
        x0 = left_margin
        y0 = page_h - top_margin - label_h
        for row in range(rows):
            for col in range(cols):
                if skip > 0:
                    skip -= 1
                    continue
                if i >= total:
                    continue
                item = label_items[i]
                x = x0 + col * (label_w + col_gap)
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
                    add_qr=not args.no_qr,
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
