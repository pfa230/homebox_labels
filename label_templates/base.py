"""Abstract base class for label templates."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

from reportlab.pdfgen.canvas import Canvas

from label_types import LabelContent, LabelGeometry


class LabelTemplate(ABC):
    """Defines the stateful interface all label templates must implement."""

    def __init__(self) -> None:
        self.reset()

    @property
    def page_size(self) -> Optional[Tuple[float, float]]:
        """Return the page size in points or ``None`` for dynamic sizing."""

        return None

    @abstractmethod
    def reset(self) -> None:
        """Clear any pagination state before a new rendering run."""

    @abstractmethod
    def next_label_geometry(self, label: LabelContent | None) -> LabelGeometry:
        """Return the geometry for the next label slot.

        Implementations may inspect ``label`` to adjust layout. The
        ``label`` argument may be ``None`` when the caller wants to advance
        pagination state without rendering content (e.g., to skip labels).
        """

    @abstractmethod
    def draw_label(
        self,
        canvas_obj: Canvas,
        content: LabelContent,
        *,
        geometry: LabelGeometry,
    ) -> None:
        """Paint ``content`` into ``geometry`` using the provided canvas."""

    def consume_page_break(self) -> bool:
        """Return True when the caller should advance to a new page."""

        return False
