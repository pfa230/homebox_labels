"""Homebox API manager that encapsulates authentication and data retrieval."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Set

from domain_types import Location, Asset

from homebox_client import ApiClient, Configuration
from homebox_client.api.authentication_api import AuthenticationApi
from homebox_client.api.locations_api import LocationsApi
from homebox_client.api.items_api import ItemsApi

# Default timeout (in seconds) for Homebox API requests.
DEFAULT_TIMEOUT = 30


@dataclass
class HomeboxApiManager:
    """Homebox label generator API helper."""

    base_url: str
    username: str
    password: str
    timeout: int = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        base_clean = (self.base_url or "").rstrip("/")
        if not base_clean:
            raise RuntimeError("Homebox base URL is required.")
        if not self.username or not self.password:
            raise RuntimeError("Homebox username and password are required.")

        self.base_url = base_clean
        self._location_id_regex: re.Pattern[str] = self._compile_location_id_regex()
        self._api_client = self._create_authenticated_client(base_clean)
        self._locations_api = LocationsApi(self._api_client)
        self._items_api = ItemsApi(self._api_client)

    @property
    def api_client(self) -> ApiClient:
        """Expose the authenticated ApiClient for advanced use cases."""

        return self._api_client

    def list_locations(self) -> List[Location]:
        """Return locations as domain objects."""

        locations_raw = self._locations_api.v1_locations_get(
            _request_timeout=self.timeout
        ) or []
        if not locations_raw:
            return []
        loc_ids: List[str] = []
        for loc in locations_raw:
            loc_id = getattr(loc, "id", "") or ""
            if isinstance(loc_id, str) and loc_id:
                loc_ids.append(loc_id)
        detail_map: Dict[str, Dict] = self.get_location_details(loc_ids)
        tree = self.get_location_tree()
        path_map = self._build_location_paths(tree)
        labels_map, asset_count_map = self.get_location_item_labels(loc_ids)

        domain: List[Location] = []
        for loc in locations_raw:
            loc_id = getattr(loc, "id", "") or ""
            detail_payload = detail_map.get(loc_id, {})
            description = (
                detail_payload.get("description")
                or getattr(loc, "description", "")
                or ""
            ).strip()
            label_names = labels_map.get(loc_id, [])
            asset_count = asset_count_map.get(loc_id, 0)

            title, content = self._split_name_content(getattr(loc, "name", "") or "")

            path_list = path_map.get(loc_id, [])
            parent = path_list[-2] if len(path_list) >= 2 else ""

            domain.append(
                Location(
                    id=loc_id,
                    display_id=title,
                    name=content,
                    parent=parent,
                    asset_count=asset_count,
                    labels=label_names,
                    description=description,
                    path=path_map.get(loc_id, []),
                )
            )
        return domain

    def get_location_tree(self) -> List[Dict]:
        """Return the hierarchical tree of locations."""

        nodes = self._locations_api.v1_locations_tree_get(
            _request_timeout=self.timeout
        ) or []
        return [node.to_dict() for node in nodes]

    def get_location_detail(self, location_id: str) -> Dict:
        """Fetch detail payload for a specific location."""

        detail = self._locations_api.v1_locations_id_get(
            location_id,
            _request_timeout=self.timeout,
        )
        return detail.to_dict()

    def get_location_details(self, loc_ids: Iterable[str]) -> Dict[str, Dict]:
        """Fetch details for the provided collection of location IDs."""

        details: Dict[str, Dict] = {}
        for loc_id in loc_ids:
            if not loc_id:
                continue
            details[loc_id] = self.get_location_detail(loc_id)
        return details

    def get_location_item_labels(
        self,
        loc_ids: Iterable[str],
        page_size: int = 100,
    ) -> tuple[Dict[str, List[str]], Dict[str, int]]:
        """Collect label lists and unique asset counts keyed by location id."""

        labels_map: Dict[str, List[str]] = {}
        counts_map: Dict[str, int] = {}
        for loc_id in loc_ids:
            if not loc_id:
                continue
            labels, count = self._fetch_labels_and_count_for_location(
                loc_id,
                page_size=page_size,
            )
            labels_map[loc_id] = labels
            counts_map[loc_id] = count
        return labels_map, counts_map

    def list_items(self, page_size: int = 100, location_id: str | None = None) -> List[Asset]:
        """Return assets as domain objects."""

        items: List[Asset] = []
        page = 1
        while True:
            response = self._items_api.v1_items_get(
                page=page,
                page_size=page_size,
                locations=[location_id] if location_id else None,
                _request_timeout=self.timeout,
            )
            page_items = response.items or []
            items.extend(self._convert_items(page_items))

            total = response.total or 0
            if not page_items or len(page_items) < page_size:
                break
            if total and page * page_size >= total:
                break
            page += 1

        return items

    def _convert_items(self, items_raw: Iterable[object] | None) -> List[Asset]:
        assets: List[Asset] = []
        for item in items_raw or []:
            item_id = getattr(item, "id", "") or ""
            label_names = []
            for lbl in getattr(item, "labels", None) or []:
                name = (getattr(lbl, "name", "") or "").strip()
                if name:
                    label_names.append(name)
            loc = getattr(item, "location", None)
            location_name = (getattr(loc, "name", "") or "").strip() if loc else ""
            location_id = (getattr(loc, "id", "") or "").strip() if loc else ""
            parent_asset_name = (
                (getattr(item, "parent_name", None) or getattr(item, "parent", None) or "")
                or ""
            )
            assets.append(
                Asset(
                    id=item_id,
                    display_id=getattr(item, "asset_id", "") or "",
                    name=getattr(item, "name", "") or "",
                    location_id=location_id,
                    location=location_name,
                    parent_asset=parent_asset_name.strip(),
                    labels=label_names,
                    description=(getattr(item, "description", "") or "").strip(),
                )
            )
        return assets

    def get_item_detail(self, item_id: str) -> Dict:
        """Fetch detail payload for a specific item."""

        detail = self._items_api.v1_items_id_get(
            item_id,
            _request_timeout=self.timeout,
        )
        return detail.to_dict()

    def get_item_details(self, item_ids: Iterable[str]) -> Dict[str, Dict]:
        """Fetch details for the provided collection of item IDs."""

        details: Dict[str, Dict] = {}
        for item_id in item_ids:
            if not item_id:
                continue
            details[item_id] = self.get_item_detail(item_id)
        return details

    def _fetch_labels_and_count_for_location(
        self,
        loc_id: str,
        page_size: int = 100,
    ) -> tuple[List[str], int]:
        """Return (sorted unique label names, unique asset count) for a location."""

        collected: Set[str] = set()
        asset_ids: Set[str] = set()
        page = 1
        while True:
            response = self._items_api.v1_items_get(
                page=page,
                page_size=page_size,
                locations=[loc_id],
                _request_timeout=self.timeout,
            )
            items = response.items or []
            for item in items:
                item_id = (getattr(item, "id", "") or "").strip()
                if item_id:
                    asset_ids.add(item_id)
                for label in getattr(item, "labels", None) or []:
                    name = (label.name or "").strip()
                    if name:
                        collected.add(name)

            total = response.total or 0
            if not items or len(items) < page_size:
                break
            if total and page * page_size >= total:
                break
            page += 1

        return sorted(collected, key=str.casefold), len(asset_ids)

    def _create_authenticated_client(self, base_url: str) -> ApiClient:
        """Authenticate against the Homebox API and return a ready client."""

        api_base = f"{base_url}/api"
        configuration = Configuration(host=api_base)
        api_client = ApiClient(configuration)
        auth_api = AuthenticationApi(api_client)
        token_response = auth_api.v1_users_login_post(
            username=self.username,
            password=self.password,
            stay_logged_in=True,
        )

        token = token_response.token
        if not token:
            raise RuntimeError("Login succeeded but did not return a token.")
        configuration.api_key["Bearer"] = token
        return ApiClient(configuration)

    @staticmethod
    def _build_location_paths(tree: List[Dict]) -> Dict[str, List[str]]:
        paths: Dict[str, List[str]] = {}

        def walk(node: Dict, ancestors: List[str]) -> None:
            if not isinstance(node, dict):
                return
            node_type = (node.get("type") or node.get("nodeType") or "").lower()
            if node_type and node_type != "location":
                return
            name = (node.get("name") or "").strip() or "Unnamed"
            current_path = ancestors + [name]
            loc_id = node.get("id")
            if loc_id:
                paths[loc_id] = current_path
            for child in node.get("children") or []:
                walk(child, current_path)

        for root in tree or []:
            walk(root, [])
        return paths

    def _compile_location_id_regex(self) -> re.Pattern[str]:
        pattern = os.getenv(
            "HOMEBOX_LOCATION_ID_REGEX",
            r"^\s*([^|]+?)\s*\|\s*(.*)$",
        ).strip()
        try:
            return re.compile(pattern)
        except re.error as exc:
            raise RuntimeError(
                f"Invalid HOMEBOX_LOCATION_ID_REGEX '{pattern}': {exc}"
            ) from exc

    def _split_name_content(self, name: str) -> tuple[str, str]:
        text = (name or "").strip()
        if not text:
            return "", ""

        match = self._location_id_regex.search(text)
        if match and match.group(1) and match.group(2) is not None:
            display_id = match.group(1).strip()
            if not display_id:
                return "", text
            cleaned_name = match.group(2).strip()
            if not cleaned_name:
                cleaned_name = display_id
            return display_id, cleaned_name
        return "", text
