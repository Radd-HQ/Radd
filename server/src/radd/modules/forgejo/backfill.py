"""Walk a repository's history and link what the webhook never saw. Idempotent:
links upsert by `vcs.ids` external ids."""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.events import service as events
from radd.config import settings
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.items import service as items_service
from radd.modules.vcs import receiving
from radd.modules.vcs.ids import branch_external_id, commit_external_id, pr_external_id
from radd.modules.vcs.types import RefStatus, VcsProvider, VcsRefType

from . import timelogs
from .models import ForgejoConnection, ForgejoRepo
from .parsing import extract_keys

logger = logging.getLogger(__name__)


@dataclass
class BackfillReport:
    branches: int = 0
    pull_requests: int = 0
    commits: int = 0
    linked: int = 0
    errors: list[str] = field(default_factory=list)
    unknown_keys: list[str] = field(default_factory=list)
    #: RADD-1260: the tracked-time mirror totals across every PR walked.
    worklogs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "branches": self.branches,
            "pull_requests": self.pull_requests,
            "commits": self.commits,
            "linked": self.linked,
            "errors": self.errors,
            # Keys that look like items but are not: usually another tracker's
            # scheme in an old message. Reported rather than silently dropped, so
            # a surprising zero has an explanation.
            "unknown_keys": sorted(set(self.unknown_keys))[:50],
            "worklogs": self.worklogs,
        }

    def absorb_time(self, report) -> None:
        for key, value in report.as_dict().items():
            if isinstance(value, int):
                self.worklogs[key] = self.worklogs.get(key, 0) + value
        if report.unmatched_authors:
            names = set(self.worklogs.get("unmatched_authors", []))
            self.worklogs["unmatched_authors"] = sorted(names | report.unmatched_authors)


class ForgejoClient:
    """The read-only slice of the Forgejo API this needs."""

    def __init__(self, connection: ForgejoConnection, transport: httpx.AsyncBaseTransport | None = None) -> None:
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

    async def __aenter__(self) -> "ForgejoClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def paged(self, path: str, params: dict[str, Any] | None = None, *, cap: int = 1000):
        page, seen = 1, 0
        while seen < cap:
            query = {**(params or {}), "page": page, "limit": settings.forgejo_api_page_size}
            response = await self._client.get(f"{self._base}/api/v1{path}", params=query)
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                return
            for row in batch:
                yield row
                seen += 1
                if seen >= cap:
                    return
            if len(batch) < settings.forgejo_api_page_size:
                return
            page += 1


async def _link(
    session: AsyncSession,
    report: BackfillReport,
    *,
    connection_id, repo,
    texts: list[str | None],
    ref_type: VcsRefType,
    external_id: str,
    title: str,
    url: str,
    status: str = "",
) -> None:
    from types import SimpleNamespace
    keys = extract_keys(*texts)
    for key in keys:
        if await items_service.find_item_by_key(session, key) is None:
            report.unknown_keys.append(key)
    plans = [SimpleNamespace(item_key=key, ref_type=ref_type, external_id=external_id,
        title=title, url=url, status=status) for key in (keys or [""])]
    links = await receiving.link_planned(session, plans, provider=VcsProvider.FORGEJO,
        actor_id=SYSTEM_ACTOR_ID, connection_id=connection_id, repo=repo)
    report.linked += receiving.count(links)



async def run(
    session: AsyncSession,
    connection: ForgejoConnection,
    repo: ForgejoRepo,
    *,
    max_commits: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BackfillReport:
    """Runs QUIET (`events.quiet`, RADD-1314): recorded and indexed, and no
    automation, webhook or notification reacts to it."""
    if not connection.active or not repo.enabled:
        from radd.exceptions import ConflictError
        raise ConflictError("repository", reason="Enable the connection and repository before importing history")
    with events.quiet():
        return await _run(session, connection, repo, max_commits=max_commits, transport=transport)


async def _run(
    session: AsyncSession,
    connection: ForgejoConnection,
    repo: ForgejoRepo,
    *,
    max_commits: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BackfillReport:
    """Branches, pull requests (+ their tracked time, RADD-1260) and
    default-branch commits, in that order.

    The commit walk is bounded (`forgejo_backfill_max_commits`) because a
    repository's history is unbounded and the useful part is recent. PRs are
    walked in full — a merged PR is the most information-dense link there is.
    """
    report = BackfillReport()
    cap = max_commits if max_commits is not None else settings.forgejo_backfill_max_commits
    web_base = f"{connection.base_url.rstrip('/')}/{repo.full_name}"

    async with ForgejoClient(connection, transport) as client:
        async for branch in client.paged(f"/repos/{repo.full_name}/branches"):
            report.branches += 1
            name = str(branch.get("name") or "")
            await _link(
                session,
                report, connection_id=connection.id, repo=repo,
                texts=[name],
                ref_type=VcsRefType.BRANCH,
                external_id=branch_external_id(repo.full_name, name),
                title=name,
                url=f"{web_base}/src/branch/{name}",
            )

        async for pull in client.paged(
            f"/repos/{repo.full_name}/pulls", {"state": "all", "sort": "recentupdate"}
        ):
            report.pull_requests += 1
            number = pull.get("number")
            status = (
                RefStatus.MERGED
                if pull.get("merged")
                else (RefStatus.CLOSED if pull.get("state") == "closed" else RefStatus.OPEN)
            )
            head_ref = ((pull.get("head") or {}).get("ref")) or ""
            await _link(
                session,
                report, connection_id=connection.id, repo=repo,
                texts=[pull.get("title"), pull.get("body"), head_ref],
                ref_type=VcsRefType.PULL_REQUEST,
                external_id=pr_external_id(repo.full_name, number),
                title=f"{pull.get('title') or ''} (#{number})".strip(),
                url=str(pull.get("html_url") or f"{web_base}/pulls/{number}"),
                status=str(status),
            )
            # RADD-1260: the PR's tracked time — one paged GET each; the seam
            # makes a repeat run a no-op. RADD-1321: only when switched on.
            if repo.mirror_time:
                try:
                    report.absorb_time(
                        await timelogs.reconcile_pull_request(
                            session,
                            connection,
                            repo,
                            full_name=repo.full_name,
                            index=number,
                            title=str(pull.get("title") or ""),
                            head_branch=head_ref,
                            body=str(pull.get("body") or ""),
                            transport=transport,
                        )
                    )
                except Exception:
                    report.errors.append("Time mirroring failed for a pull/merge request; see the server log.")
                    logger.exception("forgejo backfill %s: tracked-time mirror failed for #%s", repo.full_name, number)

        async for commit in client.paged(
            f"/repos/{repo.full_name}/commits", {"sha": repo.default_branch}, cap=cap
        ):
            report.commits += 1
            sha = str(commit.get("sha") or "")
            message = ((commit.get("commit") or {}).get("message")) or ""
            await _link(
                session,
                report, connection_id=connection.id, repo=repo,
                texts=[message],
                ref_type=VcsRefType.COMMIT,
                external_id=commit_external_id(repo.full_name, sha),
                title=message.splitlines()[0][:300] if message else sha[:12],
                url=str(commit.get("html_url") or f"{web_base}/commit/{sha}"),
            )

    logger.info("forgejo backfill %s: %s", repo.full_name, report.as_dict())
    return report
