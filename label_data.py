"""Helpers for building `LabelContent` collections from Homebox API data."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from homebox_api import HomeboxApiManager
from label_types import LabelContent

__all__ = [
    "collect_label_contents",
    "collect_label_contents_by_ids",
    "build_ui_url",
    "build_location_paths",
    "location_display_text",
    "split_name_content",
]


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
            f"Invalid --name-pattern regex '{pattern}': {exc}"
        ) from exc

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

    return _build_label_contents(
        filtered_locations,
        api_manager,
        base_ui,
    )


def collect_label_contents_by_ids(
    api_manager: HomeboxApiManager,
    base_ui: str,
    location_ids: Iterable[str],
) -> List[LabelContent]:
    """Return label payloads for the specified location ids."""

    if not location_ids:
        return []

    locations = api_manager.list_locations()
    by_id = {
        loc.get("id"): loc
        for loc in locations
        if isinstance(loc.get("id"), str)
    }
    ordered_locations = [
        by_id[loc_id]
        for loc_id in location_ids
        if loc_id in by_id
    ]
    return _build_label_contents(
        ordered_locations,
        api_manager,
        base_ui,
    )


def _build_label_contents(
    locations: Sequence[Dict],
    api_manager: HomeboxApiManager,
    base_ui: str,
) -> List[LabelContent]:
    valid_locations: List[Dict] = []
    loc_ids: List[str] = []
    for loc in locations:
        loc_id = loc.get("id")
        if isinstance(loc_id, str):
            valid_locations.append(loc)
            loc_ids.append(loc_id)

    if not loc_ids:
        return []

    tree = api_manager.get_location_tree()
    path_map = build_location_paths(tree)
    detail_map = api_manager.get_location_details(loc_ids)
    labels_map = api_manager.get_location_item_labels(loc_ids)

    base_ui_clean = (base_ui or "").rstrip("/")
    return [
        _to_label_content(
            loc,
            detail_map,
            labels_map,
            path_map,
            base_ui_clean,
        )
        for loc in valid_locations
    ]


def _to_label_content(
    location: Dict,
    detail_map: Dict[str, Dict],
    labels_map: Dict[str, List[str]],
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
    label_names = labels_map.get(loc_id, [])
    labels_text = ", ".join(label_names)

    full_path = path_map.get(loc_id, [])
    trimmed_path = full_path[:-1] if len(full_path) > 1 else []
    path_text = "->".join(trimmed_path)

    title, content = split_name_content(location.get("name") or "")

    return LabelContent(
        title=title,
        content=content,
        url=build_ui_url(base_ui, loc_id),
        location_id=loc_id,
        path_text=path_text,
        labels_text=labels_text,
        description_text=description,
    )
