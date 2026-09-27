"""The backfill harness (RADD-1435): walk a repository's history through the host's
API and link what the webhook never saw. The connector's `walk` knows the API; this
owns the client, the report, linking and the quiet run. Idempotent: links upsert by
`vcs.ids` external ids, mirrored time by the host's own entry ids."""

import logging
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.events import service as events
from radd.modules.items import service as items_service

from .. import receiving
from ..keys import PlannedLink, extract_keys
from ..timemirror import MirrorReport
from ..types import ConnectorSetting, VcsRefType

if TYPE_CHECKING:
    from .spec import ConnectorSpec

logger = logging.getLogger(__name__)

#: How many unknown keys a report lists — a surprising zero needs a reason, not a dump.
UNKNOWN_KEYS_SHOWN = 50


@dataclass
class BackfillReport:
    branches: int = 0
    pull_requests: int = 0
    commits: int = 0
    linked: int = 0
    errors: list[str] = field(default_factory=list)
    #: Keys that look like items but are not — usually another tracker's scheme
    #: in an old message. Reported so a surprising zero has an explanation.
    unknown_keys: list[str] = field(default_factory=list)
    #: The time-mirror totals across every merge/pull request walked.
    worklogs: dict[str, Any] = field(default_factory=dict)
    #: Counters only one host has (GitHub's comments, GitLab's timed merge requests).
    extra: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "branches": self.branches,
            "pull_requests": self.pull_requests,
            "commits": self.commits,
            "linked": self.linked,
            "errors": self.errors,
            "unknown_keys": sorted(set(self.unknown_keys))[:UNKNOWN_KEYS_SHOWN],
            "worklogs": self.worklogs,
            **self.extra,
        }

    def absorb_time(self, report: MirrorReport) -> None:
        for key, value in report.as_dict().items():
            if isinstance(value, int):
                self.worklogs[key] = self.worklogs.get(key, 0) + value
        if report.unmatched_authors:
            names = set(self.worklogs.get("unmatched_authors", []))
            self.worklogs["unmatched_authors"] = sorted(names | report.unmatched_authors)


class PagedClient:
    """The read-only slice of a host's REST API a walk needs. `transport` lets a
    test hand in an httpx.MockTransport instead of the network."""

    def __init__(self, spec: "ConnectorSpec", connection: Any, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._spec = spec
        self._base = connection.api_url
        self._per_page = int(spec.setting(ConnectorSetting.PAGE_SIZE))
        self._client = httpx.AsyncClient(
            headers=connection.api_headers,
            verify=connection.verify_ssl,
            timeout=spec.setting(ConnectorSetting.HTTP_TIMEOUT),
            transport=transport,
        )

    async def __aenter__(self) -> "PagedClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def paged(self, path: str, params: dict[str, Any] | None = None, *, cap: int = 1000) -> AsyncIterator[dict[str, Any]]:
        """Every row of a list endpoint, up to `cap`. A short page ends the walk,
        unless the host names the next page in a header (GitLab)."""
        paging = self._spec.paging
        page, seen = 1, 0
        while seen < cap:
            query = {**(params or {}), "page": page, paging.size_param: self._per_page}
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
            next_page = response.headers.get(paging.next_page_header, "").strip() if paging.next_page_header else ""
            if next_page:
                page = int(next_page)
            elif len(batch) < self._per_page:
                return
            else:
                page += 1


@dataclass
class BackfillRun:
    """What a connector's `walk` works with: the rows, the API client, the report."""

    session: AsyncSession
    connection: Any
    repo: Any
    client: PagedClient
    report: BackfillReport
    #: The default-branch commit walk's bound — history is unbounded, the useful part recent.
    max_commits: int
    transport: httpx.AsyncBaseTransport | None
    provider: Any

    @property
    def name(self) -> str:
        return self.repo.full_name.strip("/")

    @property
    def web_base(self) -> str:
        return f"{self.connection.base_url.rstrip('/')}/{self.name}"

    async def link(
        self, *, texts: list[str | None], ref_type: VcsRefType, external_id: str, title: str, url: str, status: str = ""
    ) -> None:
        """Link one ref to every issue its texts name (and to every issue already
        linked to it), counting the keys that name nothing."""
        keys = extract_keys(*texts)
        for key in keys:
            if await items_service.find_item_by_key(self.session, key) is None:
                self.report.unknown_keys.append(key)
        plans = [
            PlannedLink(item_key=key, ref_type=ref_type, external_id=external_id, title=title, url=url, status=status)
            for key in (keys or [""])
        ]
        links = await receiving.link_planned(
            self.session, plans, provider=self.provider, actor_id=SYSTEM_ACTOR_ID,
            connection_id=self.connection.id, repo=self.repo,
        )
        self.report.linked += receiving.count(links)

    async def mirror(self, label: str, reconcile: Awaitable[MirrorReport]) -> bool:
        """Fold one merge/pull request's mirrored time into the report. A failure
        is reported and logged; the links already made stand."""
        try:
            self.report.absorb_time(await reconcile)
            return True
        except Exception:
            self.report.errors.append(f"Time mirroring failed for {label}; see the server log.")
            logger.exception("%s backfill %s: time mirror failed for %s", self.provider.value, self.name, label)
            return False


async def run(
    spec: "ConnectorSpec",
    session: AsyncSession,
    connection: Any,
    repo: Any,
    *,
    max_commits: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BackfillReport:
    """Runs QUIET (`events.quiet`, RADD-1314): recorded and indexed, and no
    automation, webhook or notification reacts to it. Releases are never
    replayed — sweeping today's waiting work into a year-old version would be
    wrong, and the release webhook covers everything from now on."""
    if not connection.active or not repo.enabled:
        raise ConflictError("repository", reason="Enable the connection and repository before importing history")
    report = BackfillReport()
    cap = max_commits if max_commits is not None else int(spec.setting(ConnectorSetting.MAX_COMMITS))
    with events.quiet():
        async with PagedClient(spec, connection, transport) as client:
            await spec.walk(BackfillRun(
                session=session, connection=connection, repo=repo, client=client, report=report,
                max_commits=cap, transport=transport, provider=spec.provider,
            ))
    logger.info("%s backfill %s: %s", spec.provider.value, repo.full_name, report.as_dict())
    return report
