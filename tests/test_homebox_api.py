import re
# pyright: reportPrivateUsage=false
import unittest

from homebox_api import HomeboxApiManager
from homebox_client.types import UNSET


def _make_manager() -> HomeboxApiManager:
    manager = HomeboxApiManager.__new__(HomeboxApiManager)
    manager._location_id_regex = re.compile(r"^\s*([^|]+?)\s*\|\s*(.*)$")
    return manager


class HomeboxApiSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _make_manager()

    def test_split_with_id_and_name(self) -> None:
        display_id, name = self.manager._split_name_content("A1 | Shelf")
        self.assertEqual(display_id, "A1")
        self.assertEqual(name, "Shelf")

    def test_split_with_empty_name(self) -> None:
        display_id, name = self.manager._split_name_content("A1 | ")
        self.assertEqual(display_id, "A1")
        self.assertEqual(name, "A1")

    def test_split_without_pipe(self) -> None:
        display_id, name = self.manager._split_name_content("Shelf")
        self.assertEqual(display_id, "")
        self.assertEqual(name, "Shelf")

    def test_split_with_whitespace(self) -> None:
        display_id, name = self.manager._split_name_content("  A1  |  Shelf  ")
        self.assertEqual(display_id, "A1")
        self.assertEqual(name, "Shelf")


class HomeboxApiHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _make_manager()

    def test_as_str_handles_unset(self) -> None:
        self.assertEqual(self.manager._as_str(UNSET), "")
        self.assertEqual(self.manager._as_str(None), "")

    def test_as_list_handles_unset(self) -> None:
        self.assertEqual(self.manager._as_list(UNSET), [])
        self.assertEqual(self.manager._as_list(None), [])
        self.assertEqual(self.manager._as_list([1, 2]), [1, 2])

    def test_as_int_handles_unset(self) -> None:
        self.assertEqual(self.manager._as_int(UNSET), 0)
        self.assertEqual(self.manager._as_int(None), 0)
        self.assertEqual(self.manager._as_int(5), 5)


if __name__ == "__main__":
    unittest.main()
