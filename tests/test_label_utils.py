import unittest

from reportlab.pdfbase.pdfmetrics import stringWidth

from label_templates.utils import (
    center_baseline,
    shrink_fit,
    wrap_text_to_width,
    wrap_text_to_width_multiline,
)


class LabelUtilsTests(unittest.TestCase):
    def test_wrap_text_to_width_empty(self) -> None:
        self.assertEqual(list(wrap_text_to_width("", "Helvetica", 12, 100)), [])
        self.assertEqual(list(wrap_text_to_width("Hello", "Helvetica", 12, 0)), [])

    def test_wrap_text_to_width_single_line(self) -> None:
        lines = list(wrap_text_to_width("Hello world", "Helvetica", 12, 1000))
        self.assertEqual(lines, ["Hello world"])

    def test_wrap_text_to_width_enforces_width(self) -> None:
        max_width = 30
        lines = list(wrap_text_to_width("Hello world", "Helvetica", 12, max_width))
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(stringWidth(line, "Helvetica", 12), max_width)

    def test_wrap_text_to_width_multiline_returns_lines(self) -> None:
        lines, size = wrap_text_to_width_multiline(
            text="Hello world",
            font_name="Helvetica",
            font_size=12,
            max_width_pt=1000,
            max_height_pt=100,
        )
        self.assertEqual(lines, ["Hello world"])
        self.assertEqual(size, 12)

    def test_wrap_text_to_width_multiline_shrinks(self) -> None:
        lines, size = wrap_text_to_width_multiline(
            text="VeryLongWordThatWillNotFit",
            font_name="Helvetica",
            font_size=20,
            max_width_pt=10,
            max_height_pt=200,
            min_font_size=6,
        )
        self.assertTrue(lines)
        self.assertLess(size, 20)
        self.assertGreaterEqual(size, 6)

    def test_shrink_fit_respects_bounds(self) -> None:
        size = shrink_fit("Hello", 1000, max_font=20, min_font=10, font_name="Helvetica")
        self.assertEqual(size, 20)
        size = shrink_fit("Hello", 1, max_font=20, min_font=10, font_name="Helvetica")
        self.assertGreaterEqual(size, 10)
        self.assertLessEqual(size, 20)

    def test_center_baseline_bounds(self) -> None:
        baseline = center_baseline(0, 12, 100, 0, 2)
        self.assertEqual(baseline, 100)
        baseline = center_baseline(2, 12, 100, 0, 2)
        self.assertGreaterEqual(baseline, 12)
        self.assertLessEqual(baseline, 100)


if __name__ == "__main__":
    unittest.main()
