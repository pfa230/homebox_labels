"""LabelContent converters and collectors built on domain types."""

from __future__ import annotations

from typing import Iterable, List, Optional

from domain_data import collect_locations, collect_assets
from domain_types import Location, Asset
from homebox_api import HomeboxApiManager
from label_types import LabelContent

__all__ = [
    "collect_locations_label_contents",
    "collect_label_contents_by_ids",
    "collect_asset_label_contents",
    "location_to_label_content",
    "asset_to_label_content",
]


def build_ui_url(base_ui: str, loc_id: str) -> str:
    if loc_id:
        return f"{base_ui}/location/{loc_id}"
    return f"{base_ui}/locations"


def build_asset_ui_url(base_ui: str, item_id: str) -> str:
    if item_id:
        return f"{base_ui}/item/{item_id}"
    return f"{base_ui}/items"


def collect_locations_label_contents(
    api_manager: HomeboxApiManager,
    name_pattern: Optional[str],
) -> List[LabelContent]:
    locations = collect_locations(api_manager, name_pattern)
    return [location_to_label_content(loc, api_manager.base_url) for loc in locations]


def collect_label_contents_by_ids(
    api_manager: HomeboxApiManager,
    base_ui: str,
    location_ids: Iterable[str],
) -> List[LabelContent]:
    if not location_ids:
        return []

    locations = collect_locations(api_manager, None)
    by_id = {loc.id: loc for loc in locations if loc.id}
    ordered = [by_id[loc_id] for loc_id in location_ids if loc_id in by_id]
    return [location_to_label_content(loc, base_ui) for loc in ordered]


def collect_asset_label_contents(
    api_manager: HomeboxApiManager,
    name_pattern: Optional[str],
) -> List[LabelContent]:
    assets = collect_assets(api_manager, name_pattern)
    return [asset_to_label_content(asset, api_manager.base_url) for asset in assets]


def location_to_label_content(loc: Location, base_ui: str) -> LabelContent:
    base_ui_clean = base_ui.rstrip("/")
    return LabelContent(
        display_id=loc.display_id,
        name=loc.name,
        url=build_ui_url(base_ui_clean, loc.id),
        id=loc.id,
        parent=loc.parent,
        labels=loc.labels,
        description=loc.description,
    )


def asset_to_label_content(asset: Asset, base_ui: str) -> LabelContent:
    base_ui_clean = base_ui.rstrip("/")
    return LabelContent(
        display_id=asset.display_id,
        name=asset.name,
        url=build_asset_ui_url(base_ui_clean, asset.id),
        id=asset.id,
        parent=asset.location,
        labels=asset.labels,
        description=asset.description,
    )
