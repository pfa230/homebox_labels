import unittest
from typing import cast
from unittest.mock import Mock, patch

from domain_types import Asset, Location
from flask import Flask
from flask.testing import FlaskClient
from homebox_api import HomeboxApiManager
from homebox_labels_web import create_app
from werkzeug.wrappers import Response


class _FakeApiManager:
    base_url = "http://homebox"


class WebUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app: Flask = create_app(
            cast(HomeboxApiManager, _FakeApiManager()),
            base_ui="http://homebox",
        )
        self.app.config["TESTING"] = True
        self.client: FlaskClient = self.app.test_client()

    @patch("homebox_labels_web.collect_locations")
    def test_locations_default_filters_without_id(self, mock_collect: Mock) -> None:
        mock_collect.return_value = [
            Location(
                id="loc-1",
                display_id="BOX.001",
                name="Box One",
                parent="",
                asset_count=0,
            ),
            Location(
                id="loc-2",
                display_id="",
                name="NoId Name",
                parent="",
                asset_count=0,
            ),
        ]
        response: Response = self.client.get("/locations")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("BOX.001", body)
        self.assertNotIn("NoId Name", body)

    @patch("homebox_labels_web.collect_locations")
    def test_locations_with_id_disabled(self, mock_collect: Mock) -> None:
        mock_collect.return_value = [
            Location(
                id="loc-1",
                display_id="",
                name="Visible Name",
                parent="",
                asset_count=0,
            )
        ]
        response: Response = self.client.get("/locations?with_id=0")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Visible Name", body)

    def test_locations_choose_without_selection_redirects(self) -> None:
        response: Response = self.client.post("/locations/choose", data={})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/locations?error=no-selection", response.headers.get("Location", ""))

    @patch("homebox_labels_web.collect_assets")
    def test_assets_index_renders(self, mock_collect: Mock) -> None:
        mock_collect.return_value = [
            Asset(
                id="asset-1",
                display_id="BOX.001",
                name="Widget",
                location_id="loc-1",
                location="Box One",
                parent_asset="",
            )
        ]
        response: Response = self.client.get("/assets")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Widget", body)

    def test_assets_choose_without_selection_redirects(self) -> None:
        response: Response = self.client.post("/assets/choose", data={})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/assets?error=no-selection", response.headers.get("Location", ""))


if __name__ == "__main__":
    unittest.main()
