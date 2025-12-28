import unittest

from domain_types import Asset, Location
from label_templates.label_data import (
    asset_to_label_content,
    assets_to_label_contents,
    build_asset_ui_url,
    build_ui_url,
    location_to_label_content,
    locations_to_label_contents,
)


class LabelDataTests(unittest.TestCase):
    def test_build_ui_url_with_id(self) -> None:
        self.assertEqual(build_ui_url("http://homebox", "123"), "http://homebox/location/123")

    def test_build_ui_url_without_id(self) -> None:
        self.assertEqual(build_ui_url("http://homebox", ""), "http://homebox/locations")

    def test_build_asset_ui_url_with_id(self) -> None:
        self.assertEqual(build_asset_ui_url("http://homebox", "A1"), "http://homebox/item/A1")

    def test_build_asset_ui_url_without_id(self) -> None:
        self.assertEqual(build_asset_ui_url("http://homebox", ""), "http://homebox/items")

    def test_location_to_label_content_trims_base(self) -> None:
        loc = Location(
            id="loc-1",
            display_id="BOX.001",
            name="Box 1",
            parent="",
            asset_count=0,
        )
        content = location_to_label_content(loc, "http://homebox/")
        self.assertEqual(content.url, "http://homebox/location/loc-1")
        self.assertEqual(content.display_id, "BOX.001")
        self.assertEqual(content.name, "Box 1")

    def test_locations_to_label_contents(self) -> None:
        locs = [
            Location(
                id="loc-1",
                display_id="BOX.001",
                name="Box 1",
                parent="",
                asset_count=1,
            ),
            Location(
                id="loc-2",
                display_id="",
                name="Unnamed",
                parent="loc-1",
                asset_count=0,
            ),
        ]
        contents = locations_to_label_contents(locs, "http://homebox/")
        self.assertEqual(len(contents), 2)
        self.assertEqual(contents[1].url, "http://homebox/location/loc-2")

    def test_assets_to_label_contents(self) -> None:
        assets = [
            Asset(
                id="asset-1",
                display_id="BOX.001",
                name="Widget",
                location_id="loc-1",
                location="Box 1",
                parent_asset="",
            ),
        ]
        contents = assets_to_label_contents(assets, "http://homebox/")
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0].url, "http://homebox/item/asset-1")
        self.assertEqual(contents[0].parent, "Box 1")

    def test_asset_to_label_content_trims_base(self) -> None:
        asset = Asset(
            id="asset-1",
            display_id="A1",
            name="Widget",
            location_id="loc-1",
            location="Box 1",
            parent_asset="",
        )
        content = asset_to_label_content(asset, "http://homebox/")
        self.assertEqual(content.url, "http://homebox/item/asset-1")
        self.assertEqual(content.display_id, "A1")
        self.assertEqual(content.name, "Widget")


if __name__ == "__main__":
    unittest.main()
