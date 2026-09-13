"""Walk a repository's existing history and link what the webhook never saw (RADD-1129).

A webhook is deaf to everything before it was registered. Idempotence comes from
the write seam: `vcs.upsert_vcs_link` finds-or-creates by (item, provider,
external_id), and the ids here are the same ones parsing.py produces for the
webhook — running a backfill twice, or after a push, links nothing twice.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.items import service as items_service
from radd.modules.vcs import service as vcs
from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.types import VcsProvider, VcsRefType

from .models import GithubConnection, GithubRepo
from .parsing import extract_keys, pr_status

logger = logging.getLogger(__name__)


@dataclass
class BackfillReport:
    branches: int = 0
    pull_requests: int = 0
    commits: int = 0
    linked: int = 0
    unknown_keys: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "branches": self.branches,
            "pull_requests": self.pull_requests,
            "commits": self.commits,
            "linked": self.linked,
            # Keys that look like items but are not: usually another tracker's
            # scheme in an old message. Reported so a surprising zero has a reason.
            "unknown_keys": sorted(set(self.unknown_keys))[:50],
        }


def api_headers(connection: GithubConnection) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if connection.api_token:
        headers["Authorization"] = f"Bearer {connection.api_token}"
    return headers


class GithubClient:
    """The read-only slice of the GitHub REST API this needs. `transport` lets a
    test hand in an httpx.MockTransport instead of the network."""

    def __init__(self, connection: GithubConnection, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base = connection.api_url
        self._client = httpx.AsyncClient(
            headers=api_headers(connection),
            verify=connection.verify_ssl,
            timeout=settings.github_http_timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> "GithubClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def paged(self, path: str, params: dict[str, Any] | None = None, *, cap: int = 1000):
        page, seen = 1, 0
        per_page = settings.github_api_page_size
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
            if len(batch) < per_page:
                return
            page += 1


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
            provider=VcsProvider.GITHUB,
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
    connection: GithubConnection,
    repo: GithubRepo,
    *,
    max_commits: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BackfillReport:
    """Branches, pull requests and default-branch commits, in that order. The
    commit walk is bounded (`github_backfill_max_commits`); PRs are walked in
    full — a merged PR is the most information-dense link there is. Releases
    are NOT replayed: sweeping today's waiting work into a year-old version
    would be wrong, and the release webhook covers everything from now on."""
    report = BackfillReport()
    cap = max_commits if max_commits is not None else settings.github_backfill_max_commits
    web_base = f"{connection.base_url.rstrip('/')}/{repo.full_name}"
    name = repo.full_name

    async with GithubClient(connection, transport) as client:
        async for branch in client.paged(f"/repos/{name}/branches"):
            report.branches += 1
            branch_name = str(branch.get("name") or "")
            await _link(
                session,
                report,
                texts=[branch_name],
                ref_type=VcsRefType.BRANCH,
                external_id=branch_external_id(name, branch_name),
                title=branch_name,
                url=f"{web_base}/tree/{branch_name}",
            )

        async for pull in client.paged(
            f"/repos/{name}/pulls", {"state": "all", "sort": "updated", "direction": "desc"}
        ):
            report.pull_requests += 1
            number = pull.get("number")
            head_ref = ((pull.get("head") or {}).get("ref")) or ""
            title = pull.get("title") or ""
            await _link(
                session,
                report,
                texts=[title, pull.get("body"), head_ref],
                ref_type=VcsRefType.PULL_REQUEST,
                external_id=pr_external_id(name, number),
                title=f"{title[:280]} (#{number})".strip() if title else f"#{number}",
                url=str(pull.get("html_url") or f"{web_base}/pull/{number}"),
                status=str(pr_status(pull)),
            )

        async for commit in client.paged(
            f"/repos/{name}/commits", {"sha": repo.default_branch}, cap=cap
        ):
            report.commits += 1
            sha = str(commit.get("sha") or "")
            message = ((commit.get("commit") or {}).get("message")) or ""
            await _link(
                session,
                report,
                texts=[message],
                ref_type=VcsRefType.COMMIT,
                external_id=commit_external_id(name, sha),
                title=message.splitlines()[0][:300] if message else sha[:12],
                url=str(commit.get("html_url") or f"{web_base}/commit/{sha}"),
            )

    logger.info("github backfill %s: %s", name, report.as_dict())
    return report
