# Copyright 2026 the Radd authors
# SPDX-License-Identifier: Apache-2.0
"""RaddClient — thin httpx wrapper over the Radd REST API (PAT bearer auth)."""

from __future__ import annotations

from typing import Any

import httpx

from .types import DEFAULT_EVENTS_LIMIT, Event

API_PREFIX = "/api/v1"


class RaddApiError(Exception):
    """A non-2xx response from the tracker, carrying the parsed JSON error body."""

    def __init__(self, status_code: int, detail: Any, url: str) -> None:
        self.status_code = status_code
        self.detail = detail
        self.url = url
        super().__init__(f"HTTP {status_code} from {url}: {detail}")


class RaddClient:
    """Synchronous API client.

    ``get/post/patch/delete`` are raw passthroughs (path relative to ``/api/v1``,
    JSON in/out); on top sit the conveniences plugins use most: ``events``,
    ``find_item``, ``create_item``, ``update_item``, ``add_comment``.
    """

    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + API_PREFIX,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    # -- transport ---------------------------------------------------------

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._http.request(method, path, **kwargs)
        if response.is_error:
            try:
                detail: Any = response.json()
            except ValueError:
                detail = response.text
            raise RaddApiError(response.status_code, detail, str(response.request.url))
        if not response.content:
            return None
        return response.json()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json=json, **kwargs)

    def patch(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, json=json, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    # -- events ------------------------------------------------------------

    def events(self, after: int = 0, limit: int = DEFAULT_EVENTS_LIMIT) -> list[Event]:
        """Events with id > ``after``, ascending (the durable outbox)."""
        rows = self.get("/events", params={"after": after, "limit": limit})
        return [Event.from_dict(row) for row in rows]

    # -- conveniences ------------------------------------------------------

    def find_item(self, key: str) -> dict[str, Any]:
        """Fetch an item by its human key, e.g. ``TD-1234``."""
        return self.get(f"/items/by-key/{key}")

    def create_item(self, project_id: str, title: str, **fields: Any) -> dict[str, Any]:
        return self.post("/items", json={"project_id": project_id, "title": title, **fields})

    def update_item(self, item_id: str, **fields: Any) -> dict[str, Any]:
        return self.patch(f"/items/{item_id}", json=fields)

    def add_comment(self, item_id: str, body: str, **fields: Any) -> dict[str, Any]:
        return self.post(f"/items/{item_id}/comments", json={"body": body, **fields})

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> RaddClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
