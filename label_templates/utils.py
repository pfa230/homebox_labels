"""Shared helpers for label rendering templates."""

from __future__ import annotations

from typing import Iterable, List

from reportlab.pdfbase.pdfmetrics import stringWidth


def wrap_text_to_width(
    text: str,
    font_name: str,
    font_size: float,
    max_width_pt: float,
) -> Iterable[str]:
    """Wrap text into lines that fit within the specified width."""

    if not text or max_width_pt <= 0:
        return []

    words = text.split()
    if not words:
        return []

    lines: List[str] = []
    current: List[str] = []
    for word in words:
        tentative = " ".join(current + [word]) if current else word
        if stringWidth(tentative, font_name, font_size) <= max_width_pt or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def shrink_fit(
    text: str,
    max_width_pt: float,
    max_font: float,
    min_font: float,
    font_name: str,
    step: float = 0.5,
) -> float:
    """Return the largest font size that fits within ``max_width_pt``."""

    size = max_font
    step = max(step, 0.25)
    while size >= min_font and stringWidth(text, font_name, size) > max_width_pt:
        size -= step
    return max(size, min_font)
