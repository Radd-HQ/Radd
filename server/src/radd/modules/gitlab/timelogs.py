"""Time logged on a GitLab merge request, mirrored into the linked issue (RADD-1259).

GitLab has native time tracking (`/spend 1h`, `/spend 30m 2026-09-18 summary`)
and no webhook for it. Two facts make the mirror possible:

- the `merge_request` webhook's `changes` object carries `total_time_spent`
  on the delivery that added or removed time (`parsing.time_spent_changed`),
  which is WHEN to look;
- GraphQL exposes the per-entry `Timelog` rows (`id`, `timeSpent`, `spentAt`,
  `summary`, `user`) under `project.mergeRequest.timelogs`, which is WHAT to
  copy. REST has only totals.

GitLab REMOVES time by appending a negative entry (`/remove_time_spent` writes
one equal to the total), never by deleting rows — `net_entries` folds those into
the entries they cancel, so the mirror sums to GitLab's own total.

Author email: `user.publicEmail` when set; otherwise `GET /api/v4/users/:id`,
which returns `email` for an ADMIN's token (Cinesite's is) and nothing useful
for anyone else's — the identity map in Settings covers that case.

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

from .models import GitlabConnection, GitlabRepo

logger = logging.getLogger(__name__)

TIMELOGS_QUERY = """
query MrTimelogs($path: ID!, $iid: String!, $after: String) {
  project(fullPath: $path) {
    mergeRequest(iid: $iid) {
      timelogs(first: 100, after: $after) {
        nodes {
          id
          timeSpent
          spentAt
          summary
          user { id username publicEmail }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


def _gid_number(gid: str) -> str:
    """`gid://gitlab/User/42` → `42`."""
    return gid.rsplit("/", 1)[-1] if gid else ""


def spent_on(value: str) -> date:
    """The DATE part of a `spentAt` timestamp, taken as sent (UTC). A dated
    `/spend 1h 2026-09-18` is stored at NOON UTC on that date (seen live on
    18.4); an undated one at the moment it was typed. The date is read in UTC
    and never shifted — the timesheet buckets by calendar day, not by instant."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


class GitlabTimelogClient:
    """GraphQL timelogs + REST user lookup. `transport` lets a test hand in an
    httpx.MockTransport instead of the network."""

    def __init__(
        self, connection: GitlabConnection, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._connection = connection
        self._client = httpx.AsyncClient(
            headers={"PRIVATE-TOKEN": connection.api_token, "Accept": "application/json"},
            verify=connection.verify_ssl,
            timeout=settings.gitlab_http_timeout_seconds,
            transport=transport,
        )
        self._emails: dict[str, str] = {}

    async def __aenter__(self) -> "GitlabTimelogClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def timelogs(self, project_path: str, iid: int | str) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            response = await self._client.post(
                self._connection.graphql_url,
                json={
                    "query": TIMELOGS_QUERY,
                    "variables": {"path": project_path, "iid": str(iid), "after": after},
                },
            )
            response.raise_for_status()
            body = response.json()
            if body.get("errors"):
                raise RuntimeError(f"gitlab graphql: {body['errors'][0].get('message', 'error')}")
            mr = ((body.get("data") or {}).get("project") or {}).get("mergeRequest") or {}
            page = mr.get("timelogs") or {}
            nodes.extend(page.get("nodes") or [])
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                return nodes
            after = info.get("endCursor")

    async def email_for(self, user: dict[str, Any]) -> str:
        """`publicEmail` if the user set one; else the REST profile, which an
        admin's token sees in full. Cached per client."""
        public = str(user.get("publicEmail") or "").strip()
        if public:
            return public
        user_id = _gid_number(str(user.get("id") or ""))
        if not user_id:
            return ""
        if user_id not in self._emails:
            email = ""
            try:
                response = await self._client.get(f"{self._connection.api_url}/users/{user_id}")
                if response.status_code < 400:
                    email = str(response.json().get("email") or "")
            except httpx.HTTPError as exc:  # a lookup failure is "no email", not a crash
                logger.info("gitlab: user %s lookup failed: %s", user_id, exc)
            self._emails[user_id] = email
        return self._emails[user_id]


def _node_order(node: dict[str, Any]) -> int:
    """CREATION order — the numeric part of the gid, which GitLab allocates
    monotonically. NOT `spentAt`: a dated `/spend 45m 2026-09-18` carries an
    earlier `spentAt` than the reset logged after it, and sorting by date would
    let that reset eat entries added afterwards (seen live, 2026-09-19)."""
    gid = str(node.get("id") or "")
    try:
        return int(gid.rsplit("/", 1)[-1])
    except ValueError:
        return 0


def net_entries(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold GitLab's removal bookkeeping into NET entries (found live, 2026-09-19).

    GitLab never deletes a timelog on `/remove_time_spent` (or the REST
    `reset_spent_time`): it appends a NEGATIVE entry equal to the total, and
    `add_spent_time -30m` appends a partial negative. Dropping the negatives
    would mirror 2h35m onto an MR GitLab itself reports as 0 — which is what
    the first live run did. So a negative entry consumes the most recent live
    positive entries before it (LIFO), reducing their seconds; an entry consumed
    to zero disappears. Entries after a reset stand. The result sums to GitLab's
    own `totalTimeSpent`, and each surviving entry keeps its own id, so the
    mirror's upsert-by-id still holds.
    """
    live: list[dict[str, Any]] = []
    for node in sorted(nodes, key=_node_order):
        seconds = int(node.get("timeSpent") or 0)
        if seconds > 0:
            live.append({**node, "timeSpent": seconds})
            continue
        remaining = -seconds
        while remaining > 0 and live:
            last = live[-1]
            take = min(remaining, int(last["timeSpent"]))
            last["timeSpent"] = int(last["timeSpent"]) - take
            remaining -= take
            if last["timeSpent"] == 0:
                live.pop()
    return live


def to_source_entries(nodes: list[dict[str, Any]], emails: dict[str, str]) -> list[timemirror.SourceEntry]:
    """Pure: GraphQL nodes → the seam's shape, negatives folded in. `emails` is
    keyed by username."""
    entries: list[timemirror.SourceEntry] = []
    for node in net_entries(nodes):
        user = node.get("user") or {}
        username = str(user.get("username") or "")
        seconds = int(node.get("timeSpent") or 0)
        if not node.get("id") or not username or seconds <= 0:
            continue
        entries.append(
            timemirror.SourceEntry(
                external_id=str(node["id"]),
                seconds=seconds,
                spent_on=spent_on(str(node.get("spentAt") or "")),
                author_username=username,
                author_email=emails.get(username, ""),
                note=str(node.get("summary") or "").strip(),
            )
        )
    return entries


async def reconcile_merge_request(
    session: AsyncSession,
    connection: GitlabConnection,
    repo: GitlabRepo | None,
    *,
    project_path: str,
    iid: int | str,
    title: str,
    source_branch: str,
    description: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> timemirror.MirrorReport:
    """Fetch the MR's timelogs and make the linked issue's worklogs match them.

    `repo` may be None for a project with no row yet (the hook was registered
    first); the category then falls back to the instance default.
    """
    async with GitlabTimelogClient(connection, transport) as client:
        nodes = await client.timelogs(project_path, iid)
        emails: dict[str, str] = {}
        for node in nodes:
            user = node.get("user") or {}
            username = str(user.get("username") or "")
            if username and username not in emails:
                emails[username] = await client.email_for(user)
    entries = to_source_entries(nodes, emails)
    category_id = await timemirror.default_category_id(
        session, repo.time_category_id if repo is not None else None
    )
    return await timemirror.reconcile(
        session,
        provider=VcsProvider.GITLAB,
        connection_id=connection.id,
        scope=pr_external_id(project_path, iid),
        ref_texts=[source_branch, title, description],
        entries=entries,
        category_id=category_id,
        note_prefix=f"Logged on !{iid} {title}".strip()[:2000],
    )
