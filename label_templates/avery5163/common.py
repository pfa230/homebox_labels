"""Shared constants for Avery 5163 label templates."""

from __future__ import annotations

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

PAGE_SIZE = letter

LABEL_W = 4.00 * inch
LABEL_H = 2.00 * inch
COL_1_W = 1.5 * inch
COL_2_W = LABEL_W - COL_1_W

COLS = 2
ROWS = 5
SLOTS = COLS * ROWS

MARGIN_LEFT = 0.17 * inch
MARGIN_RIGHT = 0.17 * inch
MARGIN_TOP = 0.50 * inch
MARGIN_BOTTOM = 0.50 * inch

H_GAP = 0.16 * inch
V_GAP = 0.00 * inch

OFFSET_X = 0.00 * inch
OFFSET_Y = 0.00 * inch

LABEL_PADDING = 0.1 * inch
COL_1_BOTTOM_PAD = 0.15 * inch
QR_SIZE = COL_1_W - 2 * LABEL_PADDING

VERT_LABEL_PADDING = 0.1 * inch
VERT_QR_SIZE = 0.80 * LABEL_H
VERT_SECTION_GAP = 0.1 * inch
VERT_LINE_GAP = 0.06 * inch
