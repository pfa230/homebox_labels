"""Shared helpers for label rendering templates."""

from __future__ import annotations

from typing import Iterable, List

from reportlab.pdfbase.pdfmetrics import stringWidth


def wrap_text_to_width_multiline(
    text: str,
    font_name: str,
    font_size: float,
    max_width_pt: float,
    max_lines: int,
    *,
    min_font_size: float | None = None,
    step: float = 0.5,
) -> tuple[List[str], float]:
    """Wrap ``text`` to at most ``max_lines`` lines, adjusting font size.

    Returns ``(lines, chosen_font_size)``.
    """

    if not text or max_width_pt <= 0 or max_lines <= 0:
        return [], font_size

    min_font = min_font_size if min_font_size is not None else font_size
    min_font = max(min_font, 0.5)

    size = font_size
    while size >= min_font:
        wrapped = list(
            wrap_text_to_width(
                text=text,
                font_name=font_name,
                font_size=size,
                max_width_pt=max_width_pt,
            )
        )

        if wrapped and len(wrapped) <= max_lines:
            return wrapped, size

        if max_lines == 2:
            merged = " ".join(wrapped[1:])
            if stringWidth(merged, font_name, size) <= max_width_pt:
                return [wrapped[0], merged], size
        size -= step

    final_size = min_font
    final_lines = [text]
    if max_lines > 1:
        fallback_wrapped = list(
            wrap_text_to_width(
                text=text,
                font_name=font_name,
                font_size=final_size,
                max_width_pt=max_width_pt,
            )
        )
        final_lines = fallback_wrapped[:max_lines] or [text]
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
