from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class LabelContent:
    """Textual payload to render into a label."""

    display_id: str
    name: str
    url: str
    id: str = ""
    parent: str = ""
    labels: List[str] = field(default_factory=list)
    description: str = ""
    template_options: dict[str, str] | None = None


@dataclass(frozen=True)
class LabelGeometry:
    left: float
    bottom: float
    right: float
    top: float

    on_new_page: bool

    @property
    def width(self) -> float:
        return max(self.right - self.left, 0.0)

    @property
    def height(self) -> float:
        return max(self.top - self.bottom, 0.0)
