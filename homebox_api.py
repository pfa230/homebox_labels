"""Homebox API manager that encapsulates authentication and data retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from homebox_client import ApiClient, Configuration
from homebox_client.api.authentication_api import AuthenticationApi
from homebox_client.api.locations_api import LocationsApi

# Default timeout (in seconds) for Homebox API requests.
DEFAULT_TIMEOUT = 30


@dataclass
class HomeboxApiManager:
    """Thin wrapper around Homebox API endpoints used by the label generator."""

    base_url: str
    username: str
    password: str
    timeout: int = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        base_clean = self.base_url.rstrip("/")
        if not base_clean:
            raise RuntimeError("Homebox base URL is required.")
        if not self.username or not self.password:
            raise RuntimeError("Homebox username and password are required.")

        self.base_url = base_clean
        self._api_client = self._create_authenticated_client(base_clean)
        self._locations_api = LocationsApi(self._api_client)

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
