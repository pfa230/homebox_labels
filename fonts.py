"""Variable font management utilities for the Homebox label generator."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse
import urllib.request

from fontTools.ttLib import TTFont as VariableTTFont
from fontTools.varLib import instancer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as ReportLabTTFont


FONTS_DIR = Path(__file__).resolve().parent / "fonts"
FONT_SOURCES: Dict[str, str] = {
    "inter": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
}


@dataclass(frozen=True)
class FontSpec:
    """Desired font weight and size for a content block."""

    weight: float
    size: float


@dataclass(frozen=True)
class FontSettings:
    """Resolved font name/size pair registered with ReportLab."""

    font_name: str
    size: float


@dataclass(frozen=True)
class FontConfig:
    """Collection of font settings used to render a label."""

    title: FontSettings
    content: FontSettings
    label: FontSettings


class VariableFontManager:
    """Instantiate static font variants from a variable font file."""

    def __init__(self, family: str, font_path: Path) -> None:
        self.family = family
        self.font_path = font_path
        self._font_bytes = font_path.read_bytes()
        self._weight_min, self._weight_max = self._discover_weight_axis()
        self._registered: Dict[str, str] = {}

    def _discover_weight_axis(self) -> Tuple[float, float]:
        font = VariableTTFont(BytesIO(self._font_bytes))
        try:
            axis = next(ax for ax in font["fvar"].axes if ax.axisTag == "wght")
        except (KeyError, StopIteration) as exc:
            raise RuntimeError(
                f"Variable font '{self.font_path}' does not expose a wght axis."
            ) from exc
        return float(axis.minValue), float(axis.maxValue)

    def font_name_for_weight(self, weight: float) -> str:
        weight = float(weight)
        if not self._weight_min <= weight <= self._weight_max:
            raise ValueError(
                f"Font weight {weight} outside supported range "
                f"{self._weight_min:.0f}–{self._weight_max:.0f}"
            )
        key = f"{weight:.1f}"
        cached = self._registered.get(key)
        if cached:
            return cached

        font_name = f"{self.family}-w{int(round(weight))}"
        buffer = self._instantiate(weight)
        pdfmetrics.registerFont(ReportLabTTFont(font_name, buffer))
        self._registered[key] = font_name
        return font_name

    def _instantiate(self, weight: float) -> BytesIO:
        font = VariableTTFont(BytesIO(self._font_bytes))
        instancer.instantiateVariableFont(font, {"wght": weight}, inplace=True)
        buffer = BytesIO()
        font.save(buffer)
        buffer.seek(0)
        return buffer


def ensure_variable_font(family: str, url: Optional[str] = None) -> Path:
    """Ensure the requested family variable font exists locally."""

    source_url = url or FONT_SOURCES.get(family.lower())
    if not source_url:
        raise SystemExit(
            f"No download URL configured for font family '{family}'. "
            "Provide --font-url explicitly."
        )

    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = Path(urlparse(source_url).path).name or f"{family.lower()}-variable.ttf"
    destination = FONTS_DIR / filename
    if not destination.exists():
        try:
            urllib.request.urlretrieve(source_url, destination)
        except Exception as exc:  # pragma: no cover - network failure path
            raise SystemExit(f"Failed to download font '{family}': {exc}") from exc
    return destination


def build_font_config(
    family: str,
    title_spec: FontSpec,
    content_spec: FontSpec,
    label_spec: FontSpec,
    url: Optional[str] = None,
) -> FontConfig:
    """Download/register fonts and return ready-to-use settings."""

    font_path = ensure_variable_font(family, url)
    manager = VariableFontManager(family, font_path)

    title_font = FontSettings(
        font_name=manager.font_name_for_weight(title_spec.weight),
        size=title_spec.size,
    )
    content_font = FontSettings(
        font_name=manager.font_name_for_weight(content_spec.weight),
        size=content_spec.size,
    )
    label_font = FontSettings(
        font_name=manager.font_name_for_weight(label_spec.weight),
        size=label_spec.size,
    )
    return FontConfig(title=title_font, content=content_font, label=label_font)


__all__ = [
    "FontConfig",
    "FontSettings",
    "FontSpec",
    "build_font_config",
    "ensure_variable_font",
    "VariableFontManager",
]
