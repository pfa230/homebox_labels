#!/usr/bin/env python3
"""Generate Homebox location label sheets using selectable templates."""

import argparse
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

from dotenv import load_dotenv
from reportlab.pdfgen import canvas

from homebox_api import HomeboxApiManager
from label_types import LabelContent
from label_templates import get_template
from label_templates.base import LabelTemplate


def _filter_locations_by_name(
    locations: Sequence[Dict],
    pattern: Optional[str],
) -> List[Dict]:
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

    return (
        name.strip()
        if isinstance(name, str) and name.strip()
        else "Unnamed"
    )


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
            return [
                item.strip()
                for item in categories.split(",")
                if item.strip()
            ]
    return []


def build_ui_url(base_ui: str, loc_id: str) -> str:
    """Construct the dashboard URL for a location."""

    if loc_id:
        return f"{base_ui}/location/{loc_id}"
    return f"{base_ui}/locations"


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

    loc_ids = [
        loc_id
        for loc in filtered_locations
        if isinstance(loc_id := loc.get("id"), str)
    ]
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
    description = (
        detail_payload.get("description")
        or location.get("description")
        or ""
    ).strip()
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
    template: LabelTemplate,
    labels: Sequence[LabelContent],
    skip: int,
    draw_outline: bool,
) -> None:
    total = len(labels)
    skip_remaining = max(0, skip)
    index = 0

    template.reset()

    page_size = template.page_size
    canvas_kwargs = {"pagesize": page_size} if page_size else {}
    canvas_obj = canvas.Canvas(output_path, **canvas_kwargs)

    while index < total or skip_remaining > 0:
        if skip_remaining > 0:
            geometry = template.next_label_geometry(None)
            skip_remaining -= 1

            if page_size is None:
                canvas_obj.setPageSize((geometry.width, geometry.height))

            if template.consume_page_break() and (
                index < total or skip_remaining > 0
            ):
                canvas_obj.showPage()
            continue

        if index >= total:
            break

        label = labels[index]
        geometry = template.next_label_geometry(label)

        if geometry.width <= 0 or geometry.height <= 0:
            raise SystemExit(
                "Template produced non-positive geometry dimensions."
            )

        if page_size is None:
            canvas_obj.setPageSize((geometry.width, geometry.height))

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

        canvas_obj.saveState()
        canvas_obj.translate(geometry.left, geometry.bottom)
        template.draw_label(canvas_obj, label, geometry=geometry)
        canvas_obj.restoreState()

        index += 1

        if template.consume_page_break() and (
            index < total or skip_remaining > 0
        ):
            canvas_obj.showPage()

    canvas_obj.save()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for generating the Homebox label PDF."""

    parser = argparse.ArgumentParser(
        description="Homebox locations -> Avery 2x4 PDF (5163/8163)"
    )
    parser.add_argument("-o", "--output")
    parser.add_argument(
        "-s", "--skip",
        type=int,
        default=0,
        help="Number of labels to skip at start of first sheet",
    )
    parser.add_argument(
        "-n", "--name-pattern",
        default="box.*",
        help=(
            "Case-insensitive regex filter applied to location display names "
            "(default: box.*)"
        ),
    )
    parser.add_argument(
        "--base",
        default=os.getenv("HOMEBOX_API_URL"),
        help=(
            "Homebox base URL (defaults to HOMEBOX_API_URL from the "
            "environment/.env)."
        ),
    )
    parser.add_argument(
        "--username",
        default=os.getenv("HOMEBOX_USERNAME"),
        help=(
            "Homebox username (defaults to HOMEBOX_USERNAME from the "
            "environment/.env)."
        ),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("HOMEBOX_PASSWORD"),
        help=(
            "Homebox password (defaults to HOMEBOX_PASSWORD from the "
            "environment/.env)."
        ),
    )
    parser.add_argument(
        "-t", "--template",
        default="5163",
        help="Label template identifier (default: 5163).",
    )
    parser.add_argument(
        "-d", "--draw-outline",
        action="store_true",
        help="Draw outline around every label",
    )

    args = parser.parse_args(argv)

    template = get_template(args.template)

    api_manager = HomeboxApiManager(
        base_url=args.base,
        username=args.username,
        password=args.password,
    )

    output = args.output or f"locations_{args.template}.pdf"
    labels = collect_label_contents(api_manager, args.base, args.name_pattern)
    render_pdf(output, template, labels, args.skip, args.draw_outline)

    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":

    load_dotenv()

    main()
