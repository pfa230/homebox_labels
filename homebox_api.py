"""Homebox API manager that encapsulates authentication and data retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set

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
        self._api_client = self._create_authenticated_client(base_clean)
        self._locations_api = LocationsApi(self._api_client)
        self._items_api = ItemsApi(self._api_client)

    @property
    def api_client(self) -> ApiClient:
        """Expose the authenticated ApiClient for advanced use cases."""

        return self._api_client

    def list_locations(self) -> List[Dict]:
        """Return the flat list of available locations."""

        locations = self._locations_api.v1_locations_get(
            _request_timeout=self.timeout
        ) or []
        return [location.to_dict() for location in locations]

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
    ) -> Dict[str, List[str]]:
        """Collect sorted label names for every location in loc_ids."""

        labels_map: Dict[str, List[str]] = {}
        for loc_id in loc_ids:
            if not loc_id:
                continue
            labels_map[loc_id] = self._fetch_labels_for_location(
                loc_id,
                page_size=page_size,
            )
        return labels_map

    def list_items(self, page_size: int = 100) -> List[Dict]:
        """Return the list of all items/assets."""

        items = []
        page = 1
        while True:
            response = self._items_api.v1_items_get(
                page=page,
                page_size=page_size,
                _request_timeout=self.timeout,
            )
            page_items = response.items or []
            items.extend([item.to_dict() for item in page_items])

            total = response.total or 0
            if not page_items or len(page_items) < page_size:
                break
            if total and page * page_size >= total:
                break
            page += 1

        return items

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

    def _fetch_labels_for_location(
        self,
        loc_id: str,
        page_size: int = 100,
    ) -> List[str]:
        """Return sorted unique label names for all items in a location."""

        collected: Set[str] = set()
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

        return sorted(collected, key=str.casefold)

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
