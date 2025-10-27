from dataclasses import dataclass


@dataclass(frozen=True)
class LabelGeometry:
    left: float
    bottom: float
    right: float
    top: float

    @property
    def width(self) -> float:
        return max(self.right - self.left, 0.0)

    @property
    def height(self) -> float:
        return max(self.top - self.bottom, 0.0)
