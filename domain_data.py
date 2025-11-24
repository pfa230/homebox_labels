"""Domain-level data helpers (no LabelContent)."""

from __future__ import annotations

import re
from typing import List, Optional, Sequence

from homebox_api import HomeboxApiManager
from domain_types import Location, Asset

__all__ = [
    "collect_locations",
    "collect_assets",
]


def _filter_locations_by_name(
    locations: Sequence[Location],
    pattern: Optional[str],
) -> List[Location]:
    """Apply the name regex filter declared by the user."""

    if not pattern:
        return list(locations)

    try:
        name_re = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise SystemExit(
            f"Invalid --name-pattern regex '{pattern}': {exc}"
        ) from exc

    return [loc for loc in locations if name_re.search(loc.name or "")]


def location_display_text(name: str) -> str:
    """Normalize user-provided location names."""

    return (
        name.strip()
        if isinstance(name, str) and name.strip()
        else "Unnamed"
    )


def split_name_content(name: str) -> tuple[str, str]:
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


def collect_locations(
    api_manager: HomeboxApiManager,
    name_pattern: Optional[str],
) -> List[Location]:
    """Fetch locations as domain objects."""

    locations = api_manager.list_locations()
    filtered_locations = _filter_locations_by_name(locations, name_pattern)
    filtered_locations.sort(
        key=lambda loc: (loc.id if isinstance(loc, Location) else loc.get("id", "")),
        reverse=True,
    )

    return list(filtered_locations)


def collect_assets(
    api_manager: HomeboxApiManager,
    name_pattern: Optional[str],
) -> List[Asset]:
    """Fetch assets as domain objects."""

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
            if name_re.search((item.name or "").strip())
        ]

    items.sort(key=lambda item: (item.id or ""), reverse=True)

    return list(items)
