"""A Confluence Server/DC REST client (`/rest/api`, PAT or basic, storage-format bodies).

Synchronous — call via `asyncio.to_thread` with a `ConfluenceCreds`, never an ORM
row. `ConfluenceUnavailable` means "could not ask", distinct from an empty result.
"""

from __future__ import annotations

import logging
import time
from types import TracebackType
from typing import Any, BinaryIO, Iterator, Self

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
#: The bulk listing a DOWNLOAD walks. No `children.page.size`: only the
#: interactive picker needs it.
EXPAND_TREE = "ancestors,space,version,extensions.position"
#: The interactive picker's listing — adds the child count so a row knows whether
#: it can expand without a probe request of its own.
EXPAND_BROWSE = EXPAND_TREE + ",children.page.size"
EXPAND_VERSIONS = "version,body.storage"

#: A long walk against a busy Confluence sees the occasional 500 or dropped
#: connection. Three attempts with a short linear backoff turned a failed
#: 6099-page download into a completed one.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5

#: Streaming chunk for attachment downloads.
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


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
        """GET with retry on 5xx/transport errors only (a busy DC drops the odd
        request mid-walk); 4xx is a real answer and raises at once."""
        last: Exception | None = None
        for attempt in range(RETRY_ATTEMPTS):
            if attempt:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            try:
                response = self.http.get(
                    path, params={k: v for k, v in params.items() if v is not None}
                )
            except httpx.HTTPError as exc:  # transport, DNS, TLS, timeout
                last = ConfluenceUnavailable(f"could not reach Confluence: {exc}")
                continue
            if response.status_code >= 500:
                last = ConfluenceUnavailable(
                    f"Confluence returned {response.status_code} for {path}: "
                    f"{response.text[:200]}",
                    status=response.status_code,
                )
                logger.warning(
                    "confluence %s on %s (attempt %d/%d) — retrying",
                    response.status_code, path, attempt + 1, RETRY_ATTEMPTS,
                )
                continue
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
        raise last or ConfluenceUnavailable(f"could not reach Confluence for {path}")

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
        for raw in self._paged("/space", expand="description.plain", type="global"):
            out.append(
                ConfluenceSpace(
                    key=raw.get("key", ""),
                    name=raw.get("name", ""),
                    id=str(raw.get("id", "")),
                    description=(
                        ((raw.get("description") or {}).get("plain") or {}).get("value", "")
                    ),
                )
            )
        return out

    def _pages(
        self, path: str, fallback_space: str, *, expand: str = EXPAND_TREE, **params: Any
    ) -> list[ConfluencePage]:
        """Parse a listing, skipping unreadable rows (one bad row must not cost the
        whole space) and de-duplicating ids (offset paging over a live collection
        repeats rows, and a repeat would kill the download on the primary key)."""
        out: list[ConfluencePage] = []
        seen: set[str] = set()
        for raw in self._paged(path, expand=expand, **params):
            try:
                page = _page_of(raw, fallback_space)
            except Exception:  # noqa: BLE001 — one bad row, not a bad space
                logger.warning(
                    "skipping an unreadable page row from %s: id=%s",
                    path, (raw or {}).get("id"), exc_info=True,
                )
                continue
            if page.id in seen:
                logger.info("duplicate page %s in %s — already listed", page.id, path)
                continue
            seen.add(page.id)
            out.append(page)
        return out

    def space_pages(self, key: str) -> list[ConfluencePage]:
        """Every page in a space, via CQL `ORDER BY id`. `/space/{key}/content/page`
        has no stable sort: on a 6,097-page space it returned 6,107 rows, 5,787
        distinct — repeats AND silent omissions. Download-time only (~49 s); browse
        with `root_pages` + `children`."""
        return self._pages(
            "/content/search", key, cql=f'space="{key}" AND type=page ORDER BY id'
        )

    def root_pages(self, key: str) -> list[ConfluencePage]:
        """Only the TOP of a space's tree (`depth=root`): 0.6 s on a 6,099-page space,
        where the whole listing is ~61 requests and minutes — a picker, not a hang."""
        return self._pages(
            f"/space/{key}/content/page", key, expand=EXPAND_BROWSE, depth="root"
        )

    def children(self, page_id: str) -> list[ConfluencePage]:
        """Direct children — the picker's expand, so it uses the browse expand."""
        return self._pages(f"/content/{page_id}/child/page", "", expand=EXPAND_BROWSE)

    def descendants(self, page_id: str) -> list[ConfluencePage]:
        """The whole subtree under a page — the `SUBTREE` scope's resolution.

        CQL `ancestor=` with the same explicit ordering, for the same reason
        `space_pages` uses it: the paged `/descendant/page` endpoint has no stable
        sort either, and a subtree that quietly loses pages is the same failure in
        miniature.
        """
        return self._pages(
            "/content/search", "", cql=f"ancestor={page_id} AND type=page ORDER BY id"
        )

    def page(self, page_id: str) -> dict:
        """One page with its storage-format body."""
        return self._get(f"/content/{page_id}", expand=EXPAND_BODY)

    def version_body(self, page_id: str, version: int) -> dict:
        """One historical revision's body (Confluence does not reliably expand
        bodies on the version list)."""
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
            # `extensions.mediaType` is what carries `video/mp4`. Without it every
            # file imported as application/octet-stream, and a browser will not
            # play a video it is told is an opaque blob.
            self._paged(
                f"/content/{page_id}/child/attachment",
                expand="version,history,extensions.mediaType",
            )
        )

    def download_to(self, download_path: str, sink: BinaryIO) -> int:
        """Stream attachment bytes into `sink` (a SpooledTemporaryFile — recordings
        run to hundreds of MB), returning the size. `_links.download` is relative
        to the SITE root, not `/rest/api`."""
        url = f"{self.base}{download_path}"
        total = 0
        try:
            with self.http.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise ConfluenceUnavailable(
                        f"attachment download returned {response.status_code}",
                        status=response.status_code,
                    )
                for chunk in response.iter_bytes(DOWNLOAD_CHUNK_BYTES):
                    sink.write(chunk)
                    total += len(chunk)
        except httpx.HTTPError as exc:
            raise ConfluenceUnavailable(f"could not fetch attachment: {exc}") from exc
        return total

    def user_by_key(self, user_key: str) -> dict:
        """Resolve an opaque `ri:userkey` (hex, not a username) to `{username,
        displayName}`; Server/DC usually withholds email."""
        return self._get("/user", key=user_key)

    def user_by_username(self, username: str) -> dict:
        """Display name for a `ri:username` mention (a username matches, but does not read)."""
        return self._get("/user", username=username)

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


def _int(value: object, default: int = 0) -> int:
    """An int from a remote payload, else `default` (`extensions.position` is the
    string "none" on an unordered page)."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _page_of(raw: dict, fallback_space: str) -> ConfluencePage:
    ancestors = raw.get("ancestors") or []
    return ConfluencePage(
        id=str(raw.get("id", "")),
        title=raw.get("title", ""),
        space_key=((raw.get("space") or {}).get("key") or fallback_space),
        parent_id=str(ancestors[-1]["id"]) if ancestors else None,
        position=_int((raw.get("extensions") or {}).get("position"), 0),
        version=_int((raw.get("version") or {}).get("number"), 1),
        labels=tuple(
            label.get("name", "")
            for label in (((raw.get("metadata") or {}).get("labels") or {}).get("results") or [])
        ),
        # `children.page.size` when expanded; Confluence also reports it under
        # extensions on some versions. Either way an absent value means "unknown",
        # and the picker treats that as expandable rather than as a leaf — showing
        # a page as childless when it is not hides content from the selection.
        has_children=_int(
            ((raw.get("children") or {}).get("page") or {}).get("size"), 1
        ) > 0,
    )
