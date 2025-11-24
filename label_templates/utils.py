"""Shared helpers for label rendering templates."""

from __future__ import annotations

from typing import Iterable, List

from reportlab.pdfbase.pdfmetrics import stringWidth


def wrap_text_to_width_multiline(
    text: str,
    font_name: str,
    font_size: float,
    max_width_pt: float,
    max_height_pt: float,
    *,
    min_font_size: float | None = None,
    step: float = 0.5,
) -> tuple[List[str], float]:
    """Wrap ``text`` to as many lines as fit width and optional height, adjusting font size.

    Returns ``(lines, chosen_font_size)``.
    """

    if not text or max_width_pt <= 0 or max_height_pt <= 0:
        return [], font_size

    min_font = min_font_size if min_font_size is not None else font_size
    min_font = max(min_font, 0.5)

    size = font_size
    while size >= min_font:
        # Before hitting min_font, do not hard-wrap words; shrink instead.
        words = text.split()
        if words:
            widest = max(stringWidth(w, font_name, size) for w in words)
            if widest > max_width_pt and size > min_font:
                size -= step
                continue

        wrapped = list(
            wrap_text_to_width(
                text=text,
                font_name=font_name,
                font_size=size,
                max_width_pt=max_width_pt,
            )
        )

        if wrapped:
            line_height_est = size * 1.2
            if len(wrapped) * line_height_est <= max_height_pt:
                return wrapped, size
        size -= step

    # Fallback: allow hard wrap at min font size; if still empty, use original text
    fallback_lines = list(
        wrap_text_to_width(
            text=text,
            font_name=font_name,
            font_size=min_font,
            max_width_pt=max_width_pt,
        )
    ) or [text]
    final_lines = fallback_lines
    final_size = min_font
    return final_lines, final_size


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
        if stringWidth(tentative, font_name, font_size) <= max_width_pt:
            current.append(word)
            continue

        if current:
            lines.append(" ".join(current))
            current = [word]
            continue

        # single word exceeds width; perform character-level wrap
        partial = ""
        for ch in word:
            candidate = partial + ch
            if stringWidth(candidate, font_name, font_size) > max_width_pt:
                if partial:
                    lines.append(partial)
                    partial = ch
                else:
                    partial = ch
            else:
                partial = candidate
        if partial:
            current = [partial]

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
    while (
        size >= min_font
        and stringWidth(text, font_name, size) > max_width_pt
    ):
        size -= step
    return max(size, min_font)


def center_baseline(
    line_count: int,
    font_size: float,
    area_top: float,
    area_bottom: float,
    gap: float,
) -> float:
    """Return a baseline that vertically centers text inside the given area.

    ``gap`` is the vertical space between lines (not including the line height).
    """

    if line_count <= 0 or area_top <= area_bottom:
        return area_top

    area_height = area_top - area_bottom
    block_height = (line_count * font_size) + max(0, line_count - 1) * gap
    offset = max((area_height - block_height) / 2.0, 0)
    # Adjust the anchor downward by an approximate ascent to visually center the glyphs,
    # since drawString treats the y coordinate as the baseline (not the top of the glyphs).
    ascent_estimate = font_size * 0.7
    baseline = area_top - offset - ascent_estimate
    return max(area_bottom + font_size, min(baseline, area_top))
