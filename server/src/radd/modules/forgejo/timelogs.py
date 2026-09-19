"""Tracked time on a Forgejo pull request, mirrored into the linked issue (RADD-1260).

Forgejo/Gitea tracks time on issues AND pull requests (a PR is an issue) and
exposes the entries as `GET /repos/{owner}/{repo}/issues/{index}/times` →
`{id, created, time (seconds), user_id, user_name}`, paged. There is no webhook
for tracked time and the `pull_request` payload carries no total, so the
connector reconciles on EVERY pull_request delivery for that PR and on the
backfill — one paged GET each, idempotent by the seam.

Two things Forgejo lacks that GitLab has: a "spent on" date (only `created`,
the moment the entry was added — the note says so) and a summary per entry.
Author email comes from `GET /api/v1/users/{username}`, visible when the user
shows it or the token is an admin's; otherwise the identity map in Settings.

Everything after fetching is the provider-neutral seam `vcs.timemirror`.
"""

import logging
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.vcs import timemirror
from radd.modules.vcs.ids import pr_external_id
from radd.modules.vcs.types import VcsProvider

from .models import ForgejoConnection, ForgejoRepo

logger = logging.getLogger(__name__)

#: A test hands the receiver a MockTransport through here; None in production.
_TRANSPORT_FOR_TESTS: httpx.AsyncBaseTransport | None = None


def created_on(value: str) -> date:
    """The DATE part of a tracked time's `created` timestamp, read in UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


class ForgejoTimeClient:
    """Tracked times + user lookup over the Forgejo REST API. `transport` lets
    a test hand in an httpx.MockTransport instead of the network."""

    def __init__(
        self, connection: ForgejoConnection, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._base = connection.base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if connection.api_token:
            headers["Authorization"] = f"token {connection.api_token}"
        self._client = httpx.AsyncClient(
            headers=headers,
            verify=connection.verify_ssl,
            timeout=settings.forgejo_http_timeout_seconds,
            transport=transport,
        )
        self._emails: dict[str, str] = {}

    async def __aenter__(self) -> "ForgejoTimeClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def times(self, full_name: str, index: int | str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        limit = settings.forgejo_api_page_size
        while True:
            response = await self._client.get(
                f"{self._base}/api/v1/repos/{full_name}/issues/{index}/times",
                params={"page": page, "limit": limit},
            )
            if response.status_code == 404:  # time tracking off for the repo, or no PR
                return rows
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                return rows
            rows.extend(batch)
            if len(batch) < limit:
                return rows
            page += 1

    async def email_for(self, username: str) -> str:
        if username not in self._emails:
            email = ""
            try:
                response = await self._client.get(f"{self._base}/api/v1/users/{username}")
                if response.status_code < 400:
                    email = str(response.json().get("email") or "")
            except httpx.HTTPError as exc:
                logger.info("forgejo: user %s lookup failed: %s", username, exc)
            self._emails[username] = email
        return self._emails[username]


def to_source_entries(rows: list[dict[str, Any]], emails: dict[str, str]) -> list[timemirror.SourceEntry]:
    """Pure: tracked-time rows → the seam's shape. `emails` is keyed by username."""
    entries: list[timemirror.SourceEntry] = []
    for row in rows:
        username = str(row.get("user_name") or "")
        seconds = int(row.get("time") or 0)
        if not row.get("id") or not username or seconds <= 0:
            continue
        entries.append(
            timemirror.SourceEntry(
                external_id=str(row["id"]),
                seconds=seconds,
                spent_on=created_on(str(row.get("created") or "")),
                author_username=username,
                author_email=emails.get(username, ""),
            )
        )
    return entries


async def reconcile_pull_request(
    session: AsyncSession,
    connection: ForgejoConnection,
    repo: ForgejoRepo | None,
    *,
    full_name: str,
    index: int | str,
    title: str,
    head_branch: str,
    body: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> timemirror.MirrorReport:
    """Fetch the PR's tracked times and make the linked issue's worklogs match."""
    async with ForgejoTimeClient(connection, transport or _TRANSPORT_FOR_TESTS) as client:
        rows = await client.times(full_name, index)
        emails: dict[str, str] = {}
        for row in rows:
            username = str(row.get("user_name") or "")
            if username and username not in emails:
                emails[username] = await client.email_for(username)
    entries = to_source_entries(rows, emails)
    category_id = await timemirror.default_category_id(
        session, repo.time_category_id if repo is not None else None
    )
    return await timemirror.reconcile(
        session,
        provider=VcsProvider.FORGEJO,
        connection_id=connection.id,
        scope=pr_external_id(full_name, index),
        ref_texts=[head_branch, title, body],
        entries=entries,
        category_id=category_id,
        # Forgejo records WHEN the entry was added, not when the work happened.
        note_prefix=f"Tracked on #{index} {title} (dated by when it was added)".strip()[:2000],
    )
