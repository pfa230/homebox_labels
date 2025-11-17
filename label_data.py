"""Helpers for building `LabelContent` collections from Homebox API data."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from homebox_api import HomeboxApiManager
from label_types import LabelContent

__all__ = [
    "collect_locations_label_contents",
    "collect_label_contents_by_ids",
    "collect_asset_label_contents",
    "build_ui_url",
    "build_asset_ui_url",
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
    """Split a location name into the id and the name."""

    text = location_display_text(name)
    if "|" not in text:
        return "", text

    display_id, _, remainder = text.partition("|")
    display_id = display_id.strip()
    cleaned_name = remainder.strip()

    if not cleaned_name:
        # Fall back to the original text if the portion after '|' is empty
        cleaned_name = text.replace("|", " ").strip()

    return display_id, cleaned_name


def build_ui_url(base_ui: str, loc_id: str) -> str:
    """Construct the dashboard URL for a location."""

    if loc_id:
        return f"{base_ui}/location/{loc_id}"
    return f"{base_ui}/locations"


def build_asset_ui_url(base_ui: str, item_id: str) -> str:
    """Construct the dashboard URL for an asset/item."""

    if item_id:
        return f"{base_ui}/item/{item_id}"
    return f"{base_ui}/items"


def collect_locations_label_contents(
    api_manager: HomeboxApiManager,
    name_pattern: Optional[str],
) -> List[LabelContent]:
    """Fetch locations and transform them into label-ready payloads."""

    locations = api_manager.list_locations()
    filtered_locations = _filter_locations_by_name(locations, name_pattern)

    return _build_location_label_contents(
        filtered_locations,
        api_manager,
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
    return _build_location_label_contents(
        ordered_locations,
        api_manager,
    )


def _build_location_label_contents(
    locations: Sequence[Dict],
    api_manager: HomeboxApiManager,
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

    base_ui_clean = api_manager.base_url.rstrip("/")
    return [
        _location_to_label_content(
            loc,
            detail_map,
            labels_map,
            path_map,
            base_ui_clean,
        )
        for loc in valid_locations
    ]


def _location_to_label_content(
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

    title, content = split_name_content(location.get("name") or "")

    # Determine parent (immediate ancestor) from the computed path map
    path_list = path_map.get(loc_id, [])
    parent = path_list[-2] if len(path_list) >= 2 else ""

    return LabelContent(
        display_id=title,
        name=content,
        url=build_ui_url(base_ui, loc_id),
        id=loc_id,
        parent=parent,
        labels=label_names,
        description=description,
    )


def collect_asset_label_contents(
    api_manager: HomeboxApiManager,
    name_pattern: Optional[str],
) -> List[LabelContent]:
    """Fetch assets and transform them into label-ready payloads."""

    items = api_manager.list_items()

    if name_pattern:
        try:
            name_re = re.compile(name_pattern, re.IGNORECASE)
        except re.error as exc:
            raise SystemExit(
                f"Invalid --name-pattern regex '{name_pattern}': {exc}"
            ) from exc

        items = [
            item for item in items
            if name_re.search((item.get("name") or "").strip())
        ]

    return _build_asset_label_contents(items, api_manager)


def _build_asset_label_contents(
    items: Sequence[Dict],
    api_manager: HomeboxApiManager,
) -> List[LabelContent]:
    valid_items: List[Dict] = []
    item_ids: List[str] = []
    for item in items:
        item_id = item.get("id")
        if isinstance(item_id, str):
            valid_items.append(item)
            item_ids.append(item_id)

    if not item_ids:
        return []

    # detail_map = api_manager.get_item_details(item_ids)
    base_ui_clean = api_manager.base_url.rstrip("/")

    return [
        _asset_to_label_content(item,
                                # detail_map,
                                base_ui_clean)
        for item in valid_items
    ]


def _asset_to_label_content(
    item: Dict,
    # detail_map: Dict[str, Dict],
    base_ui: str,
) -> LabelContent:
    """Convert a single item payload into the printable label structure."""
    print("!!!", item)
    item_id = item.get("id") or ""
    # detail_payload = detail_map.get(item_id, {})

    # description = (
    #     detail_payload.get("description")
    #     or item.get("description")
    #     or ""
    # ).strip()

    # Get labels from the item
    labels = item.get("labels", [])
    label_names = [
        (label.get("name") or "").strip()
        for label in labels
        if isinstance(label, dict)
    ]

    # Get location name for parent
    location = item.get("location", {})
    location_name = (location.get("name") or "").strip() if isinstance(location, dict) else ""

    return LabelContent(
        display_id=item.get("assetId", ""),
        name=item.get("name", ""),
        url=build_asset_ui_url(base_ui, item_id),
        id=item_id,
        parent=location_name,
        labels=label_names,
        description=item.get("description", ""),
    )
