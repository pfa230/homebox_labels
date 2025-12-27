# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingImports=false
# pyright: reportMissingTypeStubs=false

"""Variable font management utilities for the Homebox label generator."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from typing import Union

from fontTools.ttLib import TTFont as VariableTTFont
from fontTools.varLib import instancer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as ReportLabTTFont

FONTS_DIR = Path(__file__).resolve().parent / "fonts"


@dataclass(frozen=True)
class LocalVariableFont:
    family_name: str
    filename: str


@dataclass(frozen=True)
class LocalStaticFont:
    family_name: str
    files: dict[int, str]


FontSource = Union[LocalVariableFont, LocalStaticFont]


def _font_key(name: str) -> str:
    return " ".join(name.strip().lower().split())


# family_name="InterTight",
# family_name="IBMPlexSans",
# family_name="RobotoCondensed",
# family_name="ArchivoNarrow",
# family_name="SpaceGrotesk",
# family_name="SourceSans3",
# family_name="Lexend",
# family_name="NotoSans",
# family_name="IBMPlexSansCondensed",
FONT_SOURCES: dict[str, FontSource] = {
    _font_key("Inter"): LocalVariableFont(
        family_name="Inter",
        filename="InterVariable.ttf",
    ),
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
        self._registered: dict[str, str] = {}

    def _discover_weight_axis(self) -> tuple[float, float]:
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
        self._ensure_unique_ps_name(font, weight)
        buffer = BytesIO()
        font.save(buffer)
        buffer.seek(0)
        return buffer

    def _ensure_unique_ps_name(self, font: VariableTTFont, weight: float) -> None:
        """Force a distinct PostScript name if instancer did not change it."""
        nm = font["name"]
        current_ps = nm.getName(6, 3, 1, 0x409) or nm.getName(6, 1, 0, 0)
        target_ps = self._safe_ps_name(
            f"{self.family.replace(' ', '')}-W{int(round(weight))}")
        if not current_ps or current_ps.toUnicode() == target_ps:
            return  # already unique or not resolvable

        # set PS name and related records for Win/Mac
        for plat, enc, lang in ((3, 1, 0x409), (1, 0, 0)):
            # PostScript Name
            nm.setName(target_ps, 6, plat, enc, lang)
            nm.setName(f"{self.family} {int(round(weight))}",
                       4, plat, enc, lang)  # Full Name
            nm.setName(self.family, 1, plat, enc,
                       lang)                       # Family
            nm.setName(str(int(round(weight))), 2, plat,
                       enc, lang)           # Subfamily
            # Typographic Family
            nm.setName(self.family, 16, plat, enc, lang)
            nm.setName(str(int(round(weight))), 17, plat, enc,
                       lang)          # Typographic Subfamily

    def _safe_ps_name(self, s: str) -> str:
        return re.sub(r"[^A-Za-z0-9-]", "", s)[:63]


class FontRegistry:
    def __init__(self) -> None:
        self._variable_managers: dict[str, VariableFontManager] = {}

        # map (family_name, weight) -> registered font name
        self._static_registry: dict[tuple[str, int], str] = {}

    def get_font_name(self, family_key: str, weight: float) -> str:
        info = FONT_SOURCES.get(family_key)
        if info is None:
            available = ", ".join(sorted(FONT_SOURCES))
            raise SystemExit(
                f"Unknown font family '{family_key}'. Available: {available}")

        if isinstance(info, LocalVariableFont):
            return self._get_variable_font_name(info, weight)
        return self._get_static_font_name(info, weight)

    def _get_variable_font_name(
        self, info: LocalVariableFont, weight: float
    ) -> str:
        key = _font_key(info.family_name)
        manager = self._variable_managers.get(key)
        if manager is None:
            destination = FONTS_DIR / info.filename
            if not destination.exists():
                raise SystemExit(
                    f"Font file '{destination}' for family '{info.family_name}' is missing."
                )
            manager = VariableFontManager(info.family_name, destination)
            self._variable_managers[key] = manager
        return manager.font_name_for_weight(weight)

    def _get_static_font_name(self, info: LocalStaticFont, weight: float) -> str:
        weight_int = int(round(weight))
        filename = info.files.get(weight_int)
        if filename is None:
            # pick the closest available weight
            available_weights = sorted(info.files)
            closest = min(available_weights, key=lambda w: abs(w - weight_int))
            filename = info.files[closest]
            weight_int = closest

        key = (info.family_name, weight_int)
        cached = self._static_registry.get(key)
        if cached:
            return cached

        family_dir = FONTS_DIR / _font_key(info.family_name).replace(" ", "_")
        destination = family_dir / filename
        if not destination.exists():
            raise SystemExit(
                f"Font file '{destination}' for family '{info.family_name}' is missing."
            )

        font_name = f"{info.family_name.replace(' ', '')}-w{weight_int}"
        pdfmetrics.registerFont(ReportLabTTFont(font_name, destination))
        self._static_registry[key] = font_name
        return font_name


_REGISTRY = FontRegistry()


def build_font_config(
    family: str,
    title_spec: FontSpec,
    content_spec: FontSpec,
    label_spec: FontSpec,
) -> FontConfig:
    """Download/register fonts and return ready-to-use settings."""

    key = _font_key(family)

    title_font = FontSettings(
        font_name=_REGISTRY.get_font_name(key, title_spec.weight),
        size=title_spec.size,
    )
    content_font = FontSettings(
        font_name=_REGISTRY.get_font_name(key, content_spec.weight),
        size=content_spec.size,
    )
    label_font = FontSettings(
        font_name=_REGISTRY.get_font_name(key, label_spec.weight),
        size=label_spec.size,
    )
    return FontConfig(title=title_font, content=content_font, label=label_font)


__all__ = [
    "FontConfig",
    "FontSettings",
    "FontSpec",
    "build_font_config",
]
