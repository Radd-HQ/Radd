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

from radd.modules.events import service as events
from radd.config import settings
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.items import service as items_service
from radd.modules.vcs import receiving
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
    errors: list[str] = field(default_factory=list)
    unknown_keys: list[str] = field(default_factory=list)
    #: RADD-1261: the `/spend` mirror totals across every PR walked.
    worklogs: dict[str, Any] = field(default_factory=dict)
    comments: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "branches": self.branches,
            "pull_requests": self.pull_requests,
            "commits": self.commits,
            "comments": self.comments,
            "linked": self.linked,
            "errors": self.errors,
            # Keys that look like items but are not: usually another tracker's
            # scheme in an old message. Reported so a surprising zero has a reason.
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
    links = await receiving.link_planned(session, plans, provider=VcsProvider.GITHUB,
        actor_id=SYSTEM_ACTOR_ID, connection_id=connection_id, repo=repo)
    report.linked += receiving.count(links)



async def run(
    session: AsyncSession,
    connection: GithubConnection,
    repo: GithubRepo,
    *,
    max_commits: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BackfillReport:
    """RADD-1314: the backfill runs QUIET. It replays history — every old branch,
    commit, merge request and mirrored worklog — and before RADD-1308 the only
    thing keeping that out of automations was the system actor. Quiet is the
    importers' answer (jiraimport, confluenceimport): history is recorded and
    indexed, and nothing reacts to it — no automation, webhook or notification."""
    if not connection.active or not repo.enabled:
        from radd.exceptions import ConflictError
        raise ConflictError("repository", reason="Enable the connection and repository before importing history")
    with events.quiet():
        return await _run(session, connection, repo, max_commits=max_commits, transport=transport)


async def _run(
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
                report, connection_id=connection.id, repo=repo,
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
                report, connection_id=connection.id, repo=repo,
                texts=[title, pull.get("body"), head_ref],
                ref_type=VcsRefType.PULL_REQUEST,
                external_id=pr_external_id(name, number),
                title=f"{title[:280]} (#{number})".strip() if title else f"#{number}",
                url=str(pull.get("html_url") or f"{web_base}/pull/{number}"),
                status=str(pr_status(pull)),
            )
            # RADD-1261: the PR's comments (issue + review), replayed through the
            # /spend convention as one whole-scope reconcile — only when it has
            # comments at all, so a quiet PR costs nothing. RADD-1321: and only
            # for a repository someone switched mirroring on for.
            if repo.mirror_time and (
                int(pull.get("comments") or 0) + int(pull.get("review_comments") or 0) > 0 or "comments" not in pull
            ):
                comments: list[dict[str, Any]] = []
                try:
                    async for comment in client.paged(f"/repos/{name}/issues/{number}/comments", cap=settings.github_backfill_max_comments):
                        comments.append(comment)
                    async for comment in client.paged(f"/repos/{name}/pulls/{number}/comments", cap=settings.github_backfill_max_comments):
                        comments.append(comment)
                except httpx.HTTPStatusError as exc:  # comments locked/disabled: the links still count
                    report.errors.append(f"Comments for #{number} could not be read (HTTP {exc.response.status_code}).")
                    logger.info("github backfill %s: comments of #%s unreadable (%s)", name, number, exc.response.status_code)
                report.comments += len(comments)
                if comments:
                    from . import timelogs

                    try:
                        report.absorb_time(
                            await timelogs.reconcile_pull_request(
                                session, connection, repo,
                                repo_name=name, number=number, title=title, body=str(pull.get("body") or ""),
                                head_branch=head_ref, comments=comments,
                            )
                        )
                    except Exception:
                        report.errors.append(f"Time mirroring failed for #{number}; see the server log.")
                        logger.exception("github backfill %s: /spend mirror failed for #%s", name, number)

        async for commit in client.paged(
            f"/repos/{name}/commits", {"sha": repo.default_branch}, cap=cap
        ):
            report.commits += 1
            sha = str(commit.get("sha") or "")
            message = ((commit.get("commit") or {}).get("message")) or ""
            await _link(
                session,
                report, connection_id=connection.id, repo=repo,
                texts=[message],
                ref_type=VcsRefType.COMMIT,
                external_id=commit_external_id(name, sha),
                title=message.splitlines()[0][:300] if message else sha[:12],
                url=str(commit.get("html_url") or f"{web_base}/commit/{sha}"),
            )

    logger.info("github backfill %s: %s", name, report.as_dict())
    return report
