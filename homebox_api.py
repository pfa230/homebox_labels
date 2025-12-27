"""Homebox API manager that encapsulates authentication and data retrieval."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import Iterable, TypeVar

from domain_types import Location, Asset

import httpx

from homebox_client import AuthenticatedClient, Client
from homebox_client.api.authentication.post_v1_users_login import (
    sync_detailed as login_user_detailed,
)
from homebox_client.api.items.get_v1_items import sync as get_items
from homebox_client.api.items.get_v1_items_id import sync as get_item
from homebox_client.api.locations.get_v1_locations import sync as get_locations
from homebox_client.api.locations.get_v1_locations_id import sync as get_location
from homebox_client.api.locations.get_v1_locations_tree import sync as get_locations_tree
from homebox_client.models.repo_item_out import RepoItemOut
from homebox_client.models.repo_item_summary import RepoItemSummary
from homebox_client.models.repo_location_out import RepoLocationOut
from homebox_client.models.repo_location_out_count import RepoLocationOutCount
from homebox_client.models.repo_pagination_result_repo_item_summary import (
    RepoPaginationResultRepoItemSummary,
)
from homebox_client.models.repo_tree_item import RepoTreeItem
from homebox_client.models.v1_login_form import V1LoginForm
from homebox_client.types import UNSET, Unset

T = TypeVar("T")

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
        self._client = self._create_authenticated_client(base_clean)

    @property
    def api_client(self) -> AuthenticatedClient:
        """Expose the authenticated client for advanced use cases."""

        return self._client

    def list_locations(self) -> list[Location]:
        """Return locations as domain objects."""

        locations_raw: list[RepoLocationOutCount] = (
            get_locations(client=self._client) or []
        )
        if not locations_raw:
            return []
        loc_ids: list[str] = []
        for loc in locations_raw:
            loc_id = self._as_str(loc.id)
            if loc_id:
                loc_ids.append(loc_id)
        detail_map = self.get_location_details(loc_ids)
        tree = self.get_location_tree()
        path_map = self._build_location_paths(tree)
        labels_map, asset_count_map = self.get_location_item_labels(loc_ids)

        domain: list[Location] = []
        for loc in locations_raw:
            loc_id = self._as_str(loc.id)
            detail_payload = detail_map.get(loc_id)
            description = str(
                self._as_str(detail_payload.description if detail_payload else None)
                or self._as_str(loc.description)
            ).strip()
            label_names = labels_map.get(loc_id, [])
            asset_count = asset_count_map.get(loc_id, 0)

            title, content = self._split_name_content(self._as_str(loc.name))

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

    def get_location_tree(self) -> list[RepoTreeItem]:
        """Return the hierarchical tree of locations."""

        return get_locations_tree(client=self._client) or []

    def get_location_detail(self, location_id: str) -> RepoLocationOut | None:
        """Fetch detail payload for a specific location."""

        return get_location(client=self._client, id=location_id)

    def get_location_details(self, loc_ids: Iterable[str]) -> dict[str, RepoLocationOut]:
        """Fetch details for the provided collection of location IDs."""

        details: dict[str, RepoLocationOut] = {}
        for loc_id in loc_ids:
            if not loc_id:
                continue
            detail = self.get_location_detail(loc_id)
            if detail is None:
                continue
            details[loc_id] = detail
        return details

    def get_location_item_labels(
        self,
        loc_ids: Iterable[str],
        page_size: int = 100,
    ) -> tuple[dict[str, list[str]], dict[str, int]]:
        """Collect label lists and unique asset counts keyed by location id."""

        labels_map: dict[str, list[str]] = {}
        counts_map: dict[str, int] = {}
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

    def list_items(self, page_size: int = 100, location_id: str | None = None) -> list[Asset]:
        """Return assets as domain objects."""

        items: list[Asset] = []
        page = 1
        while True:
            response: RepoPaginationResultRepoItemSummary | None = get_items(
                client=self._client,
                page=page,
                page_size=page_size,
                locations=[location_id] if location_id else UNSET,
            )
            if response is None:
                break
            page_items = self._as_list(response.items)
            items.extend(self._convert_items(page_items))

            total = self._as_int(response.total)
            if not page_items or len(page_items) < page_size:
                break
            if total and page * page_size >= total:
                break
            page += 1

        return items

    def _convert_items(self, items_raw: Iterable[RepoItemSummary] | None) -> list[Asset]:
        assets: list[Asset] = []
        for item in items_raw or []:
            item_id = self._as_str(item.id)
            label_names: list[str] = []
            for lbl in self._as_list(item.labels):
                name = self._as_str(lbl.name).strip()
                if name:
                    label_names.append(name)
            loc = item.location
            if isinstance(loc, Unset) or loc is None:
                location_name = ""
                location_id = ""
            else:
                location_name = self._as_str(loc.name).strip()
                location_id = self._as_str(loc.id).strip()
            assets.append(
                Asset(
                    id=item_id,
                    display_id=self._as_str(item.asset_id),
                    name=self._as_str(item.name),
                    location_id=location_id,
                    location=location_name,
                    parent_asset="",
                    labels=label_names,
                    description=self._as_str(item.description).strip(),
                )
            )
        return assets

    def get_item_detail(self, item_id: str) -> RepoItemOut | None:
        """Fetch detail payload for a specific item."""

        return get_item(client=self._client, id=item_id)

    def get_item_details(self, item_ids: Iterable[str]) -> dict[str, RepoItemOut]:
        """Fetch details for the provided collection of item IDs."""

        details: dict[str, RepoItemOut] = {}
        for item_id in item_ids:
            if not item_id:
                continue
            detail = self.get_item_detail(item_id)
            if detail is None:
                continue
            details[item_id] = detail
        return details

    def _fetch_labels_and_count_for_location(
        self,
        loc_id: str,
        page_size: int = 100,
    ) -> tuple[list[str], int]:
        """Return (sorted unique label names, unique asset count) for a location."""

        collected: set[str] = set()
        asset_ids: set[str] = set()
        page = 1
        while True:
            response: RepoPaginationResultRepoItemSummary | None = get_items(
                client=self._client,
                page=page,
                page_size=page_size,
                locations=[loc_id],
            )
            if response is None:
                break
            items = self._as_list(response.items)
            for item in items:
                item_id = self._as_str(item.id).strip()
                if item_id:
                    asset_ids.add(item_id)
                for label in self._as_list(item.labels):
                    name = self._as_str(label.name).strip()
                    if name:
                        collected.add(name)

            total = self._as_int(response.total)
            if not items or len(items) < page_size:
                break
            if total and page * page_size >= total:
                break
            page += 1

        return sorted(collected, key=str.casefold), len(asset_ids)

    def _create_authenticated_client(self, base_url: str) -> AuthenticatedClient:
        """Authenticate against the Homebox API and return a ready client."""

        api_base = f"{base_url}/api"
        timeout = httpx.Timeout(self.timeout)
        login_client = Client(base_url=api_base, timeout=timeout)
        login_form = V1LoginForm(
            username=self.username,
            password=self.password,
            stay_logged_in=True,
        )
        response = login_user_detailed(client=login_client, body=login_form)
        if response.status_code != HTTPStatus.OK:
            content = response.content.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Login failed ({response.status_code}): {content}"
            )
        token_response = response.parsed

        token = self._as_str(token_response.token if token_response else None)
        if not token:
            content = response.content.decode("utf-8", errors="replace")
            raise RuntimeError(
                "Login succeeded but did not return a token. "
                f"Response: {content}"
            )
        return AuthenticatedClient(base_url=api_base, token=token, timeout=timeout)

    def _build_location_paths(self, tree: list[RepoTreeItem]) -> dict[str, list[str]]:
        paths: dict[str, list[str]] = {}

        def walk(node: RepoTreeItem, ancestors: list[str]) -> None:
            node_type = self._as_str(node.type_).lower()
            if node_type and node_type != "location":
                return
            name = self._as_str(node.name).strip() or "Unnamed"
            current_path = ancestors + [name]
            loc_id = self._as_str(node.id)
            if loc_id:
                paths[loc_id] = current_path
            for child in self._as_list(node.children):
                walk(child, current_path)

        for root in tree or []:
            walk(root, [])
        return paths

    def _as_str(self, value: str | Unset | None) -> str:
        if isinstance(value, Unset) or value is None:
            return ""
        return value

    def _as_list(self, value: list[T] | Unset | None) -> list[T]:
        if isinstance(value, Unset) or value is None:
            return []
        return list(value)

    def _as_int(self, value: int | Unset | None) -> int:
        if isinstance(value, Unset) or value is None:
            return 0
        return int(value)

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
