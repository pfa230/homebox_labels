"""Abstract base class for label templates."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from label_types import LabelContent, LabelGeometry


@dataclass(frozen=True)
class TemplateOption:
    """Represents a configurable option exposed by a label template."""

    name: str
    possible_values: List[str]


class LabelTemplate(ABC):
    """Defines the stateful interface all label templates must implement."""

    def __init__(self) -> None:
        self.reset()

    @property
    def page_size(self) -> Optional[Tuple[float, float]]:
        """Return the page size in points or ``None`` for dynamic sizing."""

        return None

    @property
    def raster_dpi(self) -> int:
        """Return DPI for rasterized outputs (PNG), defaults to 300."""

        return 300

    @abstractmethod
    def reset(self) -> None:
        """Clear any pagination state before a new rendering run."""

    @abstractmethod
    def next_label_geometry(self) -> LabelGeometry:
        """Return the geometry for the next label slot.
        """

    @abstractmethod
    def render_label(
        self,
        content: LabelContent,
    ) -> bytes:
        """Return PNG bytes for ``content`` rendered in the next slot."""

    def available_options(self) -> List[TemplateOption]:
        """Return user-tunable options supported by the template."""

        return []

    def apply_options(self, selections: Dict[str, str]) -> None:
        """Apply user-selected template options."""

        return None
