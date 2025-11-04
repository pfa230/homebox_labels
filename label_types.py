from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabelContent:
    """Textual payload to render into a label."""

    title: str
    content: str
    url: str
    location_id: str = ""
    path_text: str = ""
    labels_text: str = ""
    description_text: str = ""
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
