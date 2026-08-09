"""A Confluence Server/DC REST client (spec 117).

Server/DC, not Cloud. `confluence.example.com/pages/viewpage.action?pageId=…` is
the Server/DC URL shape, and it decides three things: the REST base is
`/rest/api`, auth is PAT (Bearer) or basic, and page bodies arrive as **storage
format** — the XHTML dialect with `ac:`/`ri:` elements — rather than Cloud's ADF
JSON. A Cloud adapter would be a second client behind the same `service.py`; it is
deliberately not designed around here, because guessing at a wire format nobody
runs is how the old Jira importer ended up with a hardcoded `customfield_*`
blocklist.

Calls are synchronous and belong in `asyncio.to_thread`, which is why they take a
plain `ConfluenceCreds` and never a SQLAlchemy row. `ConfluenceUnavailable` is
distinct from "matched nothing" so a caller can tell a bad token from an empty
space.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any, Iterator, Self

import httpx

from .types import (
    ConfluenceAuthMode,
    ConfluenceCreds,
    ConfluencePage,
    ConfluenceSpace,
)

logger = logging.getLogger(__name__)

#: Confluence caps `limit` well below this in places, but 100 is accepted
#: everywhere and keeps the page count sane on a large space.
MAX_PAGE_SIZE = 100

#: `expand` values, named once. These are wire constants with no compiler behind
#: them — a typo yields a response that is missing a key rather than an error.
EXPAND_BODY = "body.storage,version,ancestors,space,metadata.labels,history"
EXPAND_TREE = "ancestors,space,version,extensions.position"
EXPAND_VERSIONS = "version,body.storage"


class ConfluenceUnavailable(Exception):
    """Confluence could not be reached, or refused the credentials. Carries an
    HTTP status when there was one (None = transport/timeout)."""

    def __init__(self, message: str, status: int | None = None):
        self.status = status
        super().__init__(message)


class ConfluenceClient:
    """One authenticated session against one Confluence instance.

    Use as a context manager for anything making more than a single call — a space
    download is hundreds of requests, and a fresh client per call means a full TCP
    + TLS handshake for each.
    """

    def __init__(self, creds: ConfluenceCreds):
        self.creds = creds
        self._http: httpx.Client | None = None

    # --- lifecycle ---

    def __enter__(self) -> Self:
        self._http = self._build()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    @property
    def base(self) -> str:
        return self.creds.base_url.rstrip("/")

    def _build(self) -> httpx.Client:
        kwargs: dict[str, Any] = {}
        headers = {"Accept": "application/json"}
        if self.creds.auth_mode is ConfluenceAuthMode.PAT:
            headers["Authorization"] = f"Bearer {self.creds.credential}"
        else:
            kwargs["auth"] = (self.creds.username, self.creds.credential)
        return httpx.Client(
            base_url=f"{self.base}/rest/api",
            headers=headers,
            timeout=self.creds.timeout_seconds,
            verify=self.creds.verify_ssl,
            follow_redirects=True,
            **kwargs,
        )

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            self._http = self._build()
        return self._http

    # --- transport ---

    def _get(self, path: str, **params: Any) -> dict:
        try:
            response = self.http.get(path, params={k: v for k, v in params.items() if v is not None})
        except httpx.HTTPError as exc:  # transport, DNS, TLS, timeout
            raise ConfluenceUnavailable(f"could not reach Confluence: {exc}") from exc
        if response.status_code >= 400:
            raise ConfluenceUnavailable(
                f"Confluence returned {response.status_code} for {path}: "
                f"{response.text[:200]}",
                status=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            # An HTML login page with a 200 is what a wrong base URL looks like.
            raise ConfluenceUnavailable(
                f"Confluence returned a non-JSON body for {path} — check the base URL"
            ) from exc

    def _paged(self, path: str, **params: Any) -> Iterator[dict]:
        """Walk `results` across pages. Confluence returns `_links.next` when there
        is more; trusting `size < limit` instead is wrong on filtered endpoints."""
        start = 0
        while True:
            payload = self._get(path, start=start, limit=MAX_PAGE_SIZE, **params)
            results = payload.get("results") or []
            yield from results
            if not results or not (payload.get("_links") or {}).get("next"):
                return
            start += len(results)

    # --- reads ---

    def whoami(self) -> dict:
        """Liveness + credential check. `/user/current` is the cheapest authed
        endpoint that fails loudly on a bad token."""
        return self._get("/user/current")

    def spaces(self) -> list[ConfluenceSpace]:
        out: list[ConfluenceSpace] = []
        for raw in self._paged("/space", expand="description.plain,homepage", type="global"):
            out.append(
                ConfluenceSpace(
                    key=raw.get("key", ""),
                    name=raw.get("name", ""),
                    id=str(raw.get("id", "")),
                    description=(
                        ((raw.get("description") or {}).get("plain") or {}).get("value", "")
                    ),
                    homepage_id=str((raw.get("homepage") or {}).get("id", "")),
                )
            )
        return out

    def space(self, key: str) -> ConfluenceSpace:
        raw = self._get(f"/space/{key}", expand="description.plain,homepage")
        return ConfluenceSpace(
            key=raw.get("key", key),
            name=raw.get("name", key),
            id=str(raw.get("id", "")),
            description=((raw.get("description") or {}).get("plain") or {}).get("value", ""),
            homepage_id=str((raw.get("homepage") or {}).get("id", "")),
        )

    def space_pages(self, key: str) -> list[ConfluencePage]:
        """Every page in a space, as metadata. Bodies come later, per page, so a
        cancelled download has not paid for content it will never store."""
        return [
            _page_of(raw, key)
            for raw in self._paged(f"/space/{key}/content/page", expand=EXPAND_TREE)
        ]

    def children(self, page_id: str) -> list[ConfluencePage]:
        return [
            _page_of(raw, "")
            for raw in self._paged(f"/content/{page_id}/child/page", expand=EXPAND_TREE)
        ]

    def descendants(self, page_id: str) -> list[ConfluencePage]:
        """The whole subtree under a page — the `SUBTREE` scope's resolution."""
        return [
            _page_of(raw, "")
            for raw in self._paged(f"/content/{page_id}/descendant/page", expand=EXPAND_TREE)
        ]

    def page(self, page_id: str) -> dict:
        """One page with its storage-format body."""
        return self._get(f"/content/{page_id}", expand=EXPAND_BODY)

    def page_versions(self, page_id: str) -> list[dict]:
        return list(self._paged(f"/content/{page_id}/version", expand="content.body.storage"))

    def version_body(self, page_id: str, version: int) -> dict:
        """One historical revision's body. Separate from `page_versions` because
        Confluence does not reliably expand bodies on the version list."""
        return self._get(f"/content/{page_id}", version=version, expand=EXPAND_VERSIONS, status="historical")

    def comments(self, page_id: str) -> list[dict]:
        return list(
            self._paged(
                f"/content/{page_id}/child/comment",
                expand="body.storage,version,history,extensions.inlineProperties,ancestors",
                depth="all",
            )
        )

    def attachments(self, page_id: str) -> list[dict]:
        return list(
            self._paged(f"/content/{page_id}/child/attachment", expand="version,history")
        )

    def download(self, download_path: str) -> bytes:
        """Attachment bytes. The `_links.download` value is relative to the site
        root, NOT to `/rest/api` — using the API client's base would 404."""
        url = f"{self.base}{download_path}"
        try:
            response = self.http.get(url)
        except httpx.HTTPError as exc:
            raise ConfluenceUnavailable(f"could not fetch attachment: {exc}") from exc
        if response.status_code >= 400:
            raise ConfluenceUnavailable(
                f"attachment download returned {response.status_code}",
                status=response.status_code,
            )
        return response.content

    def restrictions(self, page_id: str) -> dict:
        """View/edit restrictions for one page.

        Server/DC exposes these at `/content/{id}/restriction/byOperation`. An
        instance that does not (older DC) yields an empty mapping rather than
        raising: no restrictions readable must not mean every page fails, but the
        run records it, because "we could not read them" and "there were none" must
        not look the same.
        """
        try:
            return self._get(f"/content/{page_id}/restriction/byOperation")
        except ConfluenceUnavailable as exc:
            if exc.status in (403, 404):
                logger.info("restrictions unavailable for page %s: %s", page_id, exc)
                return {}
            raise


def _page_of(raw: dict, fallback_space: str) -> ConfluencePage:
    ancestors = raw.get("ancestors") or []
    history = raw.get("history") or {}
    created_by = (history.get("createdBy") or {})
    return ConfluencePage(
        id=str(raw.get("id", "")),
        title=raw.get("title", ""),
        space_key=((raw.get("space") or {}).get("key") or fallback_space),
        parent_id=str(ancestors[-1]["id"]) if ancestors else None,
        position=int(((raw.get("extensions") or {}).get("position") or 0) or 0),
        version=int(((raw.get("version") or {}).get("number") or 1)),
        created_at=history.get("createdDate", "") or "",
        updated_at=((raw.get("version") or {}).get("when") or ""),
        author=created_by.get("username", "") or created_by.get("displayName", ""),
        author_email=created_by.get("email", "") or "",
        labels=tuple(
            label.get("name", "")
            for label in (((raw.get("metadata") or {}).get("labels") or {}).get("results") or [])
        ),
    )


def browse_url(base_url: str, page_id: str) -> str:
    """The human URL for a page — what an unresolved reference degrades to."""
    return f"{base_url.rstrip('/')}/pages/viewpage.action?pageId={page_id}"
