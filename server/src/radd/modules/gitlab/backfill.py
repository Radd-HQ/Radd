"""Walk a GitLab project's history and link what the webhook never saw (RADD-1253/1259).

A webhook is deaf to everything before it was registered. Idempotence comes from
the write seams: `vcs.upsert_vcs_link` finds-or-creates by (item, provider,
external_id) with the ids `parsing.py` spells, and the timelog mirror upserts by
GitLab's own timelog id — running a backfill twice, or after a push, writes
nothing twice.

Merge requests are walked in full, and each one that REPORTS time
(`time_stats.total_time_spent > 0` on the REST object) has its per-user
entries fetched and mirrored — the historical import Hussein asked for.
"""

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.items import service as items_service
from radd.modules.vcs import service as vcs
from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.types import VcsProvider, VcsRefType

from . import timelogs
from .models import GitlabConnection, GitlabRepo
from .parsing import extract_keys, mr_status, mr_title

logger = logging.getLogger(__name__)


@dataclass
class BackfillReport:
    branches: int = 0
    merge_requests: int = 0
    commits: int = 0
    linked: int = 0
    unknown_keys: list[str] = field(default_factory=list)
    #: The time-mirror totals across every MR that reported time (RADD-1259).
    worklogs: dict[str, Any] = field(default_factory=dict)
    timed_merge_requests: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "branches": self.branches,
            "merge_requests": self.merge_requests,
            # The shared settings page reads `pull_requests`; the count is the same thing.
            "pull_requests": self.merge_requests,
            "commits": self.commits,
            "linked": self.linked,
            "unknown_keys": sorted(set(self.unknown_keys))[:50],
            "timed_merge_requests": self.timed_merge_requests,
            "worklogs": self.worklogs,
        }

    def absorb_time(self, report) -> None:
        self.timed_merge_requests += 1
        for key, value in report.as_dict().items():
            if isinstance(value, int):
                self.worklogs[key] = self.worklogs.get(key, 0) + value
        if report.unmatched_authors:
            names = set(self.worklogs.get("unmatched_authors", []))
            self.worklogs["unmatched_authors"] = sorted(names | report.unmatched_authors)


def api_headers(connection: GitlabConnection) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if connection.api_token:
        headers["PRIVATE-TOKEN"] = connection.api_token
    return headers


class GitlabClient:
    """The read-only slice of the GitLab REST API this needs. `transport` lets a
    test hand in an httpx.MockTransport instead of the network."""

    def __init__(self, connection: GitlabConnection, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base = connection.api_url
        self._client = httpx.AsyncClient(
            headers=api_headers(connection),
            verify=connection.verify_ssl,
            timeout=settings.gitlab_http_timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> "GitlabClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def paged(self, path: str, params: dict[str, Any] | None = None, *, cap: int = 1000):
        """Offset paging: GitLab answers `X-Next-Page` (empty on the last page)."""
        page, seen = 1, 0
        per_page = settings.gitlab_api_page_size
        while seen < cap:
            query = {**(params or {}), "page": page, "per_page": per_page}
            response = await self._client.get(f"{self._base}{path}", params=query)
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                return
            for row in batch:
                yield row
                seen += 1
                if seen >= cap:
                    return
            next_page = response.headers.get("X-Next-Page", "").strip()
            if not next_page:
                if len(batch) < per_page:
                    return
                page += 1
            else:
                page = int(next_page)


def project_api_path(full_name: str) -> str:
    """`group/sub/project` → `/projects/group%2Fsub%2Fproject`."""
    return f"/projects/{quote(full_name.strip('/'), safe='')}"


async def _link(
    session: AsyncSession,
    report: BackfillReport,
    *,
    texts: list[str | None],
    ref_type: VcsRefType,
    external_id: str,
    title: str,
    url: str,
    status: str = "",
) -> None:
    for key in extract_keys(*texts):
        item = await items_service.find_item_by_key(session, key)
        if item is None:
            report.unknown_keys.append(key)
            continue
        await vcs.upsert_vcs_link(
            session,
            item.id,
            provider=VcsProvider.GITLAB,
            ref_type=ref_type,
            external_id=external_id,
            title=title,
            url=url,
            status=status,
            actor_id=SYSTEM_ACTOR_ID,
        )
        report.linked += 1


async def run(
    session: AsyncSession,
    connection: GitlabConnection,
    repo: GitlabRepo,
    *,
    max_commits: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BackfillReport:
    """Branches, merge requests (+ their time), default-branch commits — in
    that order. The commit walk is bounded (`gitlab_backfill_max_commits`); MRs
    are walked in full. Releases are NOT replayed (the RADD-1129 decision)."""
    report = BackfillReport()
    cap = max_commits if max_commits is not None else settings.gitlab_backfill_max_commits
    name = repo.full_name.strip("/")
    web_base = f"{connection.base_url.rstrip('/')}/{name}"
    api = project_api_path(name)

    async with GitlabClient(connection, transport) as client:
        async for branch in client.paged(f"{api}/repository/branches"):
            report.branches += 1
            branch_name = str(branch.get("name") or "")
            await _link(
                session,
                report,
                texts=[branch_name],
                ref_type=VcsRefType.BRANCH,
                external_id=branch_external_id(name, branch_name),
                title=branch_name,
                url=str(branch.get("web_url") or f"{web_base}/-/tree/{branch_name}"),
            )

        async for mr in client.paged(
            f"{api}/merge_requests", {"state": "all", "order_by": "updated_at", "sort": "desc"}
        ):
            report.merge_requests += 1
            iid = mr.get("iid")
            title = str(mr.get("title") or "")
            source_branch = str(mr.get("source_branch") or "")
            description = str(mr.get("description") or "")
            await _link(
                session,
                report,
                texts=[source_branch, title, description],
                ref_type=VcsRefType.MERGE_REQUEST,
                external_id=pr_external_id(name, iid),
                title=mr_title({"iid": iid, "title": title}),
                url=str(mr.get("web_url") or f"{web_base}/-/merge_requests/{iid}"),
                status=mr_status(mr).value,
            )
            # RADD-1259: the historical time. Only MRs that report any — one
            # GraphQL round trip each, none for the rest.
            if int((mr.get("time_stats") or {}).get("total_time_spent") or 0) > 0:
                try:
                    time_report = await timelogs.reconcile_merge_request(
                        session,
                        connection,
                        repo,
                        project_path=name,
                        iid=iid,
                        title=title,
                        source_branch=source_branch,
                        description=description,
                        transport=transport,
                    )
                    report.absorb_time(time_report)
                except Exception:
                    logger.exception("gitlab backfill %s: timelog mirror failed for !%s", name, iid)

        async for commit in client.paged(
            f"{api}/repository/commits", {"ref_name": repo.default_branch}, cap=cap
        ):
            report.commits += 1
            sha = str(commit.get("id") or "")
            message = str(commit.get("message") or "")
            await _link(
                session,
                report,
                texts=[message],
                ref_type=VcsRefType.COMMIT,
                external_id=commit_external_id(name, sha),
                title=message.splitlines()[0][:300] if message else sha[:12],
                url=str(commit.get("web_url") or f"{web_base}/-/commit/{sha}"),
            )

    logger.info("gitlab backfill %s: %s", name, report.as_dict())
    return report
