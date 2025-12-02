from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Location:
    id: str
    display_id: str
    name: str
    parent: str
    asset_count: int = 0
    labels: List[str] = field(default_factory=list)
    description: str = ""
    path: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Asset:
    id: str
    display_id: str
    name: str
    location_id: str
    location: str
    parent_asset: str
    labels: List[str] = field(default_factory=list)
    description: str = ""
