"""Walk a repository's existing history and link what the webhook never saw (spec 111).

A webhook is deaf to everything that happened before it was registered. This
project's own issues were reconstructed from five months of commits that exist in
a repository we can read — so the integration has to be able to look backwards.

Idempotence comes free from the write seam: `vcs.upsert_vcs_link` finds-or-creates
by (item, provider, external_id), and the external ids here are the same ones the
webhook parser produces. Running a backfill twice links nothing twice.
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
from radd.modules.vcs.types import VcsProvider, VcsRefType

from .models import ForgejoConnection, ForgejoRepo
from .parsing import extract_keys
from .types import PrStatus

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
            # scheme in an old message. Reported rather than silently dropped, so
            # a surprising zero has an explanation.
            "unknown_keys": sorted(set(self.unknown_keys))[:50],
        }


class ForgejoClient:
    """The read-only slice of the Forgejo API this needs."""

    def __init__(self, connection: ForgejoConnection) -> None:
        self._base = connection.base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if connection.api_token:
            headers["Authorization"] = f"token {connection.api_token}"
        self._client = httpx.AsyncClient(
            headers=headers, verify=connection.verify_ssl, timeout=30
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
            provider=VcsProvider.FORGEJO,
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
    connection: ForgejoConnection,
    repo: ForgejoRepo,
    *,
    max_commits: int | None = None,
) -> BackfillReport:
    """Branches, pull requests and default-branch commits, in that order.

    The commit walk is bounded (`forgejo_backfill_max_commits`) because a
    repository's history is unbounded and the useful part is recent. PRs are
    walked in full — a merged PR is the most information-dense link there is.
    """
    report = BackfillReport()
    cap = max_commits if max_commits is not None else settings.forgejo_backfill_max_commits
    web_base = f"{connection.base_url.rstrip('/')}/{repo.full_name}"

    async with ForgejoClient(connection) as client:
        async for branch in client.paged(f"/repos/{repo.full_name}/branches"):
            report.branches += 1
            name = str(branch.get("name") or "")
            await _link(
                session,
                report,
                texts=[name],
                ref_type=VcsRefType.BRANCH,
                external_id=f"branch:{repo.full_name}:{name}",
                title=name,
                url=f"{web_base}/src/branch/{name}",
            )

        async for pull in client.paged(
            f"/repos/{repo.full_name}/pulls", {"state": "all", "sort": "recentupdate"}
        ):
            report.pull_requests += 1
            number = pull.get("number")
            status = (
                PrStatus.MERGED
                if pull.get("merged")
                else (PrStatus.CLOSED if pull.get("state") == "closed" else PrStatus.OPEN)
            )
            head_ref = ((pull.get("head") or {}).get("ref")) or ""
            await _link(
                session,
                report,
                texts=[pull.get("title"), pull.get("body"), head_ref],
                ref_type=VcsRefType.PULL_REQUEST,
                external_id=f"pr:{repo.full_name}:{number}",
                title=f"{pull.get('title') or ''} (#{number})".strip(),
                url=str(pull.get("html_url") or f"{web_base}/pulls/{number}"),
                status=str(status),
            )

        async for commit in client.paged(
            f"/repos/{repo.full_name}/commits", {"sha": repo.default_branch}, cap=cap
        ):
            report.commits += 1
            sha = str(commit.get("sha") or "")
            message = ((commit.get("commit") or {}).get("message")) or ""
            await _link(
                session,
                report,
                texts=[message],
                ref_type=VcsRefType.COMMIT,
                external_id=f"commit:{repo.full_name}:{sha}",
                title=message.splitlines()[0][:300] if message else sha[:12],
                url=str(commit.get("html_url") or f"{web_base}/commit/{sha}"),
            )

    logger.info("forgejo backfill %s: %s", repo.full_name, report.as_dict())
    return report
