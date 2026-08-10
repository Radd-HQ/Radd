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
import time
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
#: The bulk listing a DOWNLOAD walks. No `children.page.size`: only an
#: interactive picker needs it, and there is no reason to pay for it across the
#: ~61 requests a real space takes.
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
        """One GET, retried on a TRANSIENT failure.

        Downloading a real space is ~61 requests, and a busy Confluence returns an
        occasional 500 or drops a connection somewhere in the middle. Without
        this, one hiccup 40 pages in threw away the whole walk and reported
        "download failed" — measured against the live instance, where the same
        offset succeeded on the very next attempt.

        Only 5xx and transport errors retry. A 401/403/404 is a real answer about
        credentials or a missing space, and repeating it just delays the report.
        """
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

    def _pages(
        self, path: str, fallback_space: str, *, expand: str = EXPAND_TREE, **params: Any
    ) -> list[ConfluencePage]:
        """Parse a listing, SKIPPING any row that cannot be read.

        One unreadable page must not cost the caller the whole space. Before this,
        a single row with an unexpected shape raised out of the list comprehension
        and took the entire listing with it — which is what turned one unordered
        page into "download failed" for a space of hundreds, and into an empty
        tree browser with no error at all.
        """
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
            # Offset pagination over a live collection REPEATS rows: walking a
            # 6107-page space returned one page in two different windows, and the
            # snapshot's primary key then killed the download 375 bodies in. The
            # listing is the right place to fix it — a caller should never have to
            # know that "every page in this space" might say one of them twice.
            if page.id in seen:
                logger.info("duplicate page %s in %s — already listed", page.id, path)
                continue
            seen.add(page.id)
            out.append(page)
        return out

    def space_pages(self, key: str) -> list[ConfluencePage]:
        """EVERY page in a space, as metadata.

        Uses CQL with an explicit **ORDER BY id**, not `/space/{key}/content/page`.
        That endpoint has no stable sort, and offset pagination over an unstably
        ordered collection both REPEATS and DROPS rows: measured against a real
        6097-page space it returned 6107 rows of which only 5787 were distinct —
        320 repeats, and ~310 pages never returned at all. The repeats were loud
        (a primary-key violation killed the download); the omissions were silent,
        which is far worse for an importer whose whole promise is that nothing is
        lost. The same query ordered by id returns 6097 rows, 6097 distinct.

        A download-time call, not a browse-time one — ~49s for that space. Use
        `root_pages` + `children` to let a person browse.
        """
        return self._pages(
            "/content/search", key, cql=f'space="{key}" AND type=page ORDER BY id'
        )

    def root_pages(self, key: str) -> list[ConfluencePage]:
        """Only the TOP of a space's tree (`depth=root`).

        0.6s against a 6099-page space, versus minutes for the whole thing — which
        is the difference between a scope picker and a hang.
        """
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


def _int(value: object, default: int = 0) -> int:
    """A number out of a REMOTE payload, or the default.

    Confluence's `extensions.position` is an integer for a page whose order was
    set by hand and the literal STRING `"none"` for one that inherits it — so a
    bare `int()` crashes on the first unordered page in a space. That is one
    unordered page out of hundreds, which is why it survived every test built
    from hand-written fixtures and only appeared against a real instance.

    Nothing in a JSON body from another system is guaranteed to be the type its
    field name suggests, so every numeric read here goes through this.
    """
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _page_of(raw: dict, fallback_space: str) -> ConfluencePage:
    ancestors = raw.get("ancestors") or []
    history = raw.get("history") or {}
    created_by = (history.get("createdBy") or {})
    return ConfluencePage(
        id=str(raw.get("id", "")),
        title=raw.get("title", ""),
        space_key=((raw.get("space") or {}).get("key") or fallback_space),
        parent_id=str(ancestors[-1]["id"]) if ancestors else None,
        position=_int((raw.get("extensions") or {}).get("position"), 0),
        version=_int((raw.get("version") or {}).get("number"), 1),
        created_at=history.get("createdDate", "") or "",
        updated_at=((raw.get("version") or {}).get("when") or ""),
        author=created_by.get("username", "") or created_by.get("displayName", ""),
        author_email=created_by.get("email", "") or "",
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


def browse_url(base_url: str, page_id: str) -> str:
    """The human URL for a page — what an unresolved reference degrades to."""
    return f"{base_url.rstrip('/')}/pages/viewpage.action?pageId={page_id}"
