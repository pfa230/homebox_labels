"""Variable font management utilities for the Homebox label generator."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional, Tuple, Union
from urllib.parse import urlparse
import urllib.request

from fontTools.ttLib import TTFont as VariableTTFont
from fontTools.varLib import instancer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as ReportLabTTFont


FONTS_DIR = Path(__file__).resolve().parent / "fonts"


@dataclass(frozen=True)
class VariableFontInfo:
    family_name: str
    url: str


@dataclass(frozen=True)
class StaticFontInfo:
    family_name: str
    base_url: str
    files: Dict[int, str]


FontSource = Union[VariableFontInfo, StaticFontInfo]


def _font_key(name: str) -> str:
    return " ".join(name.strip().lower().split())


FONT_SOURCES: Dict[str, FontSource] = {
    _font_key("Inter"): VariableFontInfo(
        family_name="Inter",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
    ),
    _font_key("Inter Tight"): VariableFontInfo(
        family_name="InterTight",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/intertight/InterTight%5Bwght%5D.ttf",
    ),
    _font_key("IBM Plex Sans"): VariableFontInfo(
        family_name="IBMPlexSans",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexsans/IBMPlexSans%5Bwdth,wght%5D.ttf",
    ),
    _font_key("Roboto Condensed"): VariableFontInfo(
        family_name="RobotoCondensed",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/robotocondensed/RobotoCondensed%5Bwght%5D.ttf",
    ),
    _font_key("Archivo Narrow"): VariableFontInfo(
        family_name="ArchivoNarrow",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/archivonarrow/ArchivoNarrow%5Bwght%5D.ttf",
    ),
    _font_key("Space Grotesk"): VariableFontInfo(
        family_name="SpaceGrotesk",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf",
    ),
    _font_key("Source Sans 3"): VariableFontInfo(
        family_name="SourceSans3",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/sourcesans3/SourceSans3%5Bwght%5D.ttf",
    ),
    _font_key("Lexend"): VariableFontInfo(
        family_name="Lexend",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/lexend/Lexend%5Bwght%5D.ttf",
    ),
    _font_key("Noto Sans"): VariableFontInfo(
        family_name="NotoSans",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/notosans/NotoSans%5Bwdth,wght%5D.ttf",
    ),
    _font_key("IBM Plex Sans Condensed"): StaticFontInfo(
        family_name="IBMPlexSansCondensed",
        base_url="https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexsanscondensed/",
        files={
            100: "IBMPlexSansCondensed-Thin.ttf",
            200: "IBMPlexSansCondensed-ExtraLight.ttf",
            300: "IBMPlexSansCondensed-Light.ttf",
            400: "IBMPlexSansCondensed-Regular.ttf",
            500: "IBMPlexSansCondensed-Medium.ttf",
            600: "IBMPlexSansCondensed-SemiBold.ttf",
            700: "IBMPlexSansCondensed-Bold.ttf",
        },
    ),
    _font_key("Atkinson Hyperlegible"): StaticFontInfo(
        family_name="AtkinsonHyperlegible",
        base_url="https://raw.githubusercontent.com/google/fonts/main/ofl/atkinsonhyperlegible/",
        files={
            400: "AtkinsonHyperlegible-Regular.ttf",
            700: "AtkinsonHyperlegible-Bold.ttf",
        },
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


class FontRegistry:
    def __init__(self) -> None:
        self._variable_managers: Dict[str, VariableFontManager] = {}
    
        # map (family_name, weight) -> registered font name
        self._static_registry: Dict[Tuple[str, int], str] = {}

    def get_font_name(self, family_key: str, weight: float, override_url: Optional[str] = None) -> str:
        info = FONT_SOURCES.get(family_key)
        if info is None:
            available = ", ".join(sorted(FONT_SOURCES))
            raise SystemExit(f"Unknown font family '{family_key}'. Available: {available}")

        if isinstance(info, VariableFontInfo):
            return self._get_variable_font_name(info, weight, override_url)
        return self._get_static_font_name(info, weight)

    def _download(self, url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            return
        try:
            urllib.request.urlretrieve(url, destination)
        except Exception as exc:  # pragma: no cover
            raise SystemExit(f"Failed to download font from '{url}': {exc}") from exc

    def _get_variable_font_name(
        self, info: VariableFontInfo, weight: float, override_url: Optional[str]
    ) -> str:
        key = _font_key(info.family_name)
        manager = self._variable_managers.get(key)
        if manager is None or override_url:
            url = override_url or info.url
            filename = Path(urlparse(url).path).name or f"{info.family_name.lower()}-variable.ttf"
            destination = FONTS_DIR / filename
            self._download(url, destination)
            manager = VariableFontManager(info.family_name, destination)
            self._variable_managers[key] = manager
        return manager.font_name_for_weight(weight)

    def _get_static_font_name(self, info: StaticFontInfo, weight: float) -> str:
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
        self._download(info.base_url + filename, destination)

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
    url: Optional[str] = None,
) -> FontConfig:
    """Download/register fonts and return ready-to-use settings."""

    key = _font_key(family)

    title_font = FontSettings(
        font_name=_REGISTRY.get_font_name(key, title_spec.weight, override_url=url),
        size=title_spec.size,
    )
    content_font = FontSettings(
        font_name=_REGISTRY.get_font_name(key, content_spec.weight, override_url=url),
        size=content_spec.size,
    )
    label_font = FontSettings(
        font_name=_REGISTRY.get_font_name(key, label_spec.weight, override_url=url),
        size=label_spec.size,
    )
    return FontConfig(title=title_font, content=content_font, label=label_font)


__all__ = [
    "FontConfig",
    "FontSettings",
    "FontSpec",
    "build_font_config",
]
