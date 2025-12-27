from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Location:
    id: str
    display_id: str
    name: str
    parent: str
    asset_count: int = 0
    labels: list[str] = field(default_factory=list[str])
    description: str = ""
    path: list[str] = field(default_factory=list[str])


@dataclass(frozen=True)
class Asset:
    id: str
    display_id: str
    name: str
    location_id: str
    location: str
    parent_asset: str
    labels: list[str] = field(default_factory=list[str])
    description: str = ""
