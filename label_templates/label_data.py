"""LabelContent converters built on domain types."""

from __future__ import annotations

from typing import Iterable, List

from domain_types import Location, Asset
from label_templates.label_types import LabelContent

__all__ = [
    "locations_to_label_contents",
    "assets_to_label_contents",
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


def locations_to_label_contents(
    locations: Iterable[Location],
    base_ui: str,
) -> List[LabelContent]:
    base_ui_clean = base_ui.rstrip("/")
    return [location_to_label_content(loc, base_ui_clean) for loc in locations]


def assets_to_label_contents(
    assets: Iterable[Asset],
    base_ui: str,
) -> List[LabelContent]:
    base_ui_clean = base_ui.rstrip("/")
    return [asset_to_label_content(asset, base_ui_clean) for asset in assets]


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
