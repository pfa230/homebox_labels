#!/usr/bin/env python3
"""Generate Homebox location label sheets using selectable templates."""

import argparse
import os
import re
import sys
from typing import Dict, List, Optional, Sequence, Tuple

from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from homebox_api import HomeboxApiManager
from label_types import LabelContent, LabelGeometry
from label_templates import get_template


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
    trimmed_path = full_path[:-1] if len(full_path) > 1 else []
    path_text = "->".join(trimmed_path)

    title, content = split_name_content(location.get("name") or "")
    return LabelContent(
        title=title,
        content=content,
        url=build_ui_url(base_ui, loc_id),
        path_text=path_text,
        categories_text=categories_text,
    )


def render_pdf(
    output_path: str,
    template_module,
    labels: Sequence[LabelContent],
    skip: int,
    *,
    draw_outline: bool = True,
) -> None:
    total = len(labels)
    skip_remaining = max(0, skip)
    index = 0

    if hasattr(template_module, "get_label_geometry"):
        canvas_obj = canvas.Canvas(output_path)
        while index < total:
            label = labels[index]
            geom = template_module.get_label_geometry(label)
            width = geom.width
            height = geom.height
            if width <= 0 or height <= 0:
                raise SystemExit("Template produced non-positive geometry dimensions.")

            canvas_obj.setPageSize((width, height))

            if draw_outline:
                canvas_obj.saveState()
                canvas_obj.setLineWidth(0.5)
                canvas_obj.rect(geom.left, geom.bottom, width, height)
                canvas_obj.restoreState()

            canvas_obj.saveState()
            canvas_obj.translate(geom.left, geom.bottom)
            template_module.draw_label(canvas_obj, label, geometry=geom)
            canvas_obj.restoreState()

            index += 1
            if index < total:
                canvas_obj.showPage()

        canvas_obj.save()
        return

    grid = template_module.get_label_grid()
    if not grid:
        raise SystemExit("Template returned an empty label grid.")

    page_size = getattr(template_module, "PAGE_SIZE", letter)
    canvas_obj = canvas.Canvas(output_path, pagesize=page_size)

    while True:
        for label_geom in grid:
            if skip_remaining > 0:
                skip_remaining -= 1
                continue
            if index >= total:
                break

            if draw_outline:
                canvas_obj.saveState()
                canvas_obj.setLineWidth(0.5)
                canvas_obj.rect(
                    label_geom.left,
                    label_geom.bottom,
                    label_geom.width,
                    label_geom.height,
                )
                canvas_obj.restoreState()

            canvas_obj.saveState()
            canvas_obj.translate(label_geom.left, label_geom.bottom)
            template_module.draw_label(canvas_obj, labels[index], geometry=label_geom)
            canvas_obj.restoreState()
            index += 1

        if index >= total and skip_remaining <= 0:
            break
        canvas_obj.showPage()

    canvas_obj.save()


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
        "--template",
        default="5163",
        help="Label template identifier (default: 5163).",
    )
    args = parser.parse_args(argv)

    template_module = get_template(args.template)

    api_manager = HomeboxApiManager(
        base_url=args.base,
        username=args.username,
        password=args.password,
    )

    labels = collect_label_contents(api_manager, args.base, args.name_pattern)
    render_pdf(args.output, template_module, labels, args.skip)

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":

    load_dotenv()

    main()
