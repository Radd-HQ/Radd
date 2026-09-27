"""Every connector's receiver, around its parser (RADD-1435): `accept` authenticates
and claims a delivery; `deliver_push`/`deliver_change` link the refs the parser
planned and fire the connector's triggers once per issue; `release_published`
handles a published release. The parser and the per-host CI and time handling
stay with the connector."""

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.items import service as items

from . import policies, service, triggers
from .keys import PlannedLink
from .models import ItemVcsLink, VcsDelivery
from .triggers import HostAuthor, RefAction, emit_ref, host_author, ref_of
from .types import VcsProvider, VcsRefType

#: Linked issues → the links this delivery wrote for each, in delivery order.
LinksByItem = dict[uuid.UUID, list[ItemVcsLink]]


def nothing() -> dict[str, Any]:
    """Nothing linked, nothing fired — the answer to a delivery a receiver ignores."""
    return {"linked": 0, "triggered": 0}


async def claim_delivery(session, *, provider, connection_id, delivery_id, event_type, body):
    """Claim after authentication, atomically with processing; rollbacks allow retry.

    Missing IDs are processed normally. Include the event and body because some
    hosts reuse an event UUID across related webhook notifications.
    """
    if not delivery_id:
        return True
    from sqlalchemy.dialects.postgresql import insert
    digest = hashlib.sha256(delivery_id.encode() + b"\0" + event_type.encode() + b"\0" + body).hexdigest()
    return await session.scalar(insert(VcsDelivery).values(provider=str(provider), connection_id=connection_id, digest=digest)
                                .on_conflict_do_nothing().returning(VcsDelivery.digest)) is not None


@dataclass(frozen=True)
class Delivery:
    """An authenticated, claimed webhook delivery."""

    spec: Any  # the connector's ConnectorSpec
    payload: dict
    connection: Any
    #: The enabled repository the payload names on the signing connection; None
    #: when the payload names none.
    repo: Any | None
    kind: str
    #: The repository as the payload spells it (what the triggers carry).
    repo_name: str

    @property
    def provider(self) -> VcsProvider:
        return self.spec.provider

    @property
    def author(self) -> HostAuthor | None:
        return host_author(self.payload, self.connection.id)


async def accept(
    session: AsyncSession,
    store: Any,
    *,
    raw_body: bytes,
    credential: str,
    delivery_id: str,
    kind_of: Callable[[dict], str],
) -> Delivery | None:
    """Parse, authenticate (`ConnectorStore.resolve_for_payload`: the one active
    host whose secret verifies, and the named repository enabled on THAT host)
    and claim a delivery. Refuses with 403; None = already processed."""
    spec = store.spec
    provider = spec.provider.value
    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise ForbiddenError(f"{provider} webhook body is not JSON") from None
    if not isinstance(payload, dict):
        raise ForbiddenError(f"{provider} webhook body is not an object")
    resolved = await store.resolve_for_payload(session, payload, raw_body, credential)
    if resolved is None:
        # Nothing configured, the wrong credential, an inactive host, or a
        # repository not enabled on the verifying host: one answer.
        raise ForbiddenError(f"bad {provider} webhook {spec.credential}")
    connection, repo = resolved
    kind = kind_of(payload)
    if not await claim_delivery(session, provider=spec.provider, connection_id=connection.id,
            delivery_id=delivery_id, event_type=kind, body=raw_body):
        return None
    return Delivery(spec, payload, connection, repo, kind, spec.repo_name(payload))


async def link_planned(
    session: AsyncSession,
    planned: Iterable[PlannedLink],
    *,
    provider: VcsProvider,
    actor_id: uuid.UUID | None,
    connection_id: uuid.UUID | None = None,
    repo=None,
) -> LinksByItem:
    """Upsert every planned link whose key names an existing issue; a key that
    names nothing is skipped silently (text is full of things shaped like keys)."""
    by_ref: dict[str, list[PlannedLink]] = {}
    for plan in planned:
        by_ref.setdefault(plan.external_id, []).append(plan)
    out: LinksByItem = {}
    for external_id, plans in by_ref.items():
        plan = plans[0]
        targets = {}
        # Keep historical associations current even after a key is removed.
        for link in await service.links_for_refs(session, provider=provider,
                external_ids=[external_id], connection_id=connection_id):
            item = await items.require_item(session, link.item_id)
            targets[item.id] = item
        for candidate in plans:
            item = await items.find_item_by_key(session, candidate.item_key) if candidate.item_key else None
            if item is not None:
                targets[item.id] = item
        for item in targets.values():
            if repo is not None and not repo.link_all_projects and item.project_id != repo.project_id:
                continue
            link = await service.upsert_vcs_link(
                session, item.id, provider=provider, connection_id=connection_id,
                ref_type=plan.ref_type, external_id=plan.external_id,
                title=plan.title, url=plan.url, status=plan.status, actor_id=actor_id,
            )
            out.setdefault(item.id, []).append(link)
    return out


def count(links: LinksByItem) -> int:
    return sum(len(rows) for rows in links.values())


async def _link(session: AsyncSession, delivery: Delivery, planned: Iterable[PlannedLink]) -> LinksByItem:
    return await link_planned(
        session, planned, provider=delivery.provider, actor_id=SYSTEM_ACTOR_ID,
        connection_id=delivery.connection.id, repo=delivery.repo,
    )


async def deliver_push(session: AsyncSession, delivery: Delivery, planned: Iterable[PlannedLink]) -> dict[str, Any]:
    """A push: link its branch and commits, and fire the connector's push
    trigger once per issue they name."""
    links = await _link(session, delivery, planned)
    fired = await fire_push(
        session, delivery.spec.triggers.pushed, links,
        provider=delivery.provider, repo=delivery.repo_name,
        branch=str(delivery.payload.get("ref") or "").removeprefix("refs/heads/"),
        actor_id=SYSTEM_ACTOR_ID, author=delivery.author,
    )
    return {"linked": count(links), "triggered": fired}


async def deliver_change(
    session: AsyncSession,
    delivery: Delivery,
    planned: Iterable[PlannedLink],
    *,
    action: RefAction | None,
    ref_extra: Mapping[str, Any],
    changes: list[dict[str, Any]],
) -> dict[str, Any]:
    """A merge/pull request delivery: link it, fire the trigger for what the
    delivery DID (None = nothing a trigger is for), and — when the repository's
    own switch is on (RADD-1369) — move the issues a merge names to waiting."""
    links = await _link(session, delivery, planned)
    result: dict[str, Any] = {"linked": count(links), "triggered": 0}
    if action is None:
        return result
    result["triggered"] = await fire_ref_action(
        session, delivery.spec.triggers.for_action(action), links,
        provider=delivery.provider, repo=delivery.repo_name, action=action,
        ref_extra=ref_extra, actor_id=SYSTEM_ACTOR_ID, author=delivery.author, changes=changes,
    )
    if action is RefAction.MERGED and getattr(delivery.repo, "move_on_merge", False):
        result["moved"] = await policies.move_merged(session, delivery.repo, list(links), actor_id=SYSTEM_ACTOR_ID)
    return result


async def release_published(
    session: AsyncSession,
    spec: Any,
    repo: Any | None,
    *,
    repo_name: str,
    tag: str,
    name: str,
    notes: str,
    url: str,
) -> dict[str, Any]:
    """A release the host PUBLISHED (the connector decides which deliveries are
    that): fire "<Host>: release published", and record the version and sweep
    waiting work only when the repository's "Publish version on release" switch
    is on (RADD-1369) — otherwise that is an automation's call (RADD-1310)."""
    version = triggers.version_from_tag(tag)
    if not version:
        return nothing()
    await triggers.emit_release(
        session, spec.triggers.release_published,
        connection_id=getattr(repo, "connection_id", None),
        entity_type=spec.entities.REPO,
        entity_id=repo.id if repo is not None else repo_name,
        provider=spec.provider,
        repo=repo_name,
        project_id=getattr(repo, "project_id", None),
        actor_id=SYSTEM_ACTOR_ID,
        version=version,
        tag=tag,
        name=name,
        notes=notes,
        url=url,
    )
    shipped = await policies.publish_release(session, repo, version=version, actor_id=SYSTEM_ACTOR_ID, name=name, notes=notes)
    return {"linked": 0, "triggered": 1, **({"shipped": shipped} if getattr(repo, "publish_on_release", False) else {})}


async def fire_ref_action(
    session: AsyncSession,
    trigger: StrEnum,
    links: LinksByItem,
    *,
    provider: VcsProvider,
    repo: str,
    action: RefAction,
    ref_extra: Mapping[str, Any],
    actor_id: uuid.UUID | None,
    author: HostAuthor | None = None,
    changes: list[dict[str, Any]] | None = None,
) -> int:
    """A merge/pull request was opened, merged, closed or updated: one event per
    issue it names. An update with nothing meaningful changed fires nothing."""
    if action is RefAction.UPDATED and not changes:
        return 0
    for rows in links.values():
        await emit_ref(
            session, trigger, rows[0],
            provider=provider, repo=repo, actor_id=actor_id,
            payload={"action": action.value, "ref": ref_of(rows[0], **ref_extra)},
            author=author,
            changes=changes if action is RefAction.UPDATED else None,
        )
    return len(links)


async def fire_push(
    session: AsyncSession,
    trigger: StrEnum,
    links: LinksByItem,
    *,
    provider: VcsProvider,
    repo: str,
    branch: str,
    actor_id: uuid.UUID | None,
    author: HostAuthor | None = None,
) -> int:
    """A push named these issues (in the branch name or a commit message): one
    event per issue, carrying the branch and the commits that named it."""
    for rows in links.values():
        branch_link = next((row for row in rows if row.ref_type == VcsRefType.BRANCH), rows[0])
        commits = [
            {"title": row.title, "url": row.url} for row in rows if row.ref_type == VcsRefType.COMMIT
        ]
        await emit_ref(
            session, trigger, branch_link,
            provider=provider, repo=repo, actor_id=actor_id,
            payload={"branch": branch, "ref": ref_of(branch_link), "commits": commits},
            author=author,
        )
    return len(links)


async def fire_ci(
    session: AsyncSession,
    trigger: StrEnum,
    stamped: Iterable[ItemVcsLink],
    *,
    provider: VcsProvider,
    repo: str,
    state: str,
    url: str,
    actor_id: uuid.UUID | None,
    name: str = "", sha: str = "", run_id: int | None = None,
) -> int:
    """CI finished for a ref: one event per issue linked to it (a branch and its
    head commit may both be linked from the same issue — that is still one)."""
    by_item: LinksByItem = {}
    for link in stamped:
        by_item.setdefault(link.item_id, []).append(link)
    for rows in by_item.values():
        await emit_ref(
            session, trigger, rows[0],
            provider=provider, repo=repo, actor_id=actor_id,
            payload={"ref": ref_of(rows[0]), "ci": {"state": state, "url": url, "name": name, "sha": sha, "run_id": run_id}},
        )
    return len(by_item)
