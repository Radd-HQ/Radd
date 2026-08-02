"""Approval request/vote lifecycle on workflow transitions (spec 71).

The workflow guard reaches this module through two deferred, feature-detected
seams — `approved_target_state_ids` (does the item hold a consumable unlock for
a target state?) and `consume` (spend the unlock after a successful move, called
by items.update_item). Everything else is ordinary request-scoped service work:
flush, never commit; cross-module via public service functions only.

Rule params are SNAPSHOTTED onto the request; only team MEMBERSHIP resolves
live at vote time (spec 71 known simplification — team edits change the
electorate mid-flight, entry edits don't).

Spec 107: approvers are PER-ENTRY rules ([{kind, id, name, required?}]) — a
user entry needs that person's approval, a team entry needs `required`
approvals from CURRENT members, and the request approves only when EVERY
entry is satisfied. A team shrunk below its `required` makes the entry
unsatisfiable (cancel the request / edit the rule) — deliberate: deleting
people must never quietly lower an approval bar.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth import authz, service as auth
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEntity
from radd.modules.items.schemas import ItemUpdate
from radd.modules.teams import service as teams_service
from radd.modules.workflow import service as workflow, transitions as workflow_transitions
from radd.modules.workflow.guards import TransitionError
from radd.modules.workflow.models import WorkflowTransition
from radd.modules.workflow.types import TransitionCheck
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from radd.modules.workflow.types import ApproverKind

from .models import ApprovalRequest, ApprovalVote
from .schemas import (
    ApprovalEntryRead,
    ApprovalRequestCreate,
    ApprovalRequestRead,
    ApprovalUserRef,
    ApprovalVoteCreate,
    ApprovalVoteRead,
    ItemApprovalsRead,
    PendingApprovalRead,
    RequestableState,
    VoteResult,
)
from .types import (
    LIVE_STATUSES,
    ApprovalEntity,
    ApprovalEvent,
    ApprovalStatus,
    ApprovalVerdict,
)

_LIVE = [status.value for status in LIVE_STATUSES]


# --- the workflow/items seams (deferred imports on their side) ---


async def approved_target_state_ids(session: AsyncSession, item_id: uuid.UUID) -> set[str]:
    """Guard seam: string state ids this item holds a consumable APPROVED
    request for — `require_approval` passes iff the target is in this set."""
    result = await session.execute(
        select(ApprovalRequest.to_state_id).where(
            ApprovalRequest.item_id == item_id,
            ApprovalRequest.status == ApprovalStatus.APPROVED.value,
        )
    )
    return {str(state_id) for state_id in result.scalars()}


async def consume(
    session: AsyncSession, item_id: uuid.UUID, to_state_id: uuid.UUID
) -> None:
    """Items seam: a successful move into an approved target SPENDS the unlock —
    the request flips to `applied`, so one approval unlocks exactly one move."""
    request = await session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.item_id == item_id,
            ApprovalRequest.to_state_id == to_state_id,
            ApprovalRequest.status == ApprovalStatus.APPROVED.value,
        )
    )
    if request is not None:
        request.status = ApprovalStatus.APPLIED.value
        await session.flush()


# --- helpers ---


def _approval_params(row: WorkflowTransition | None) -> dict | None:
    """The require_approval rule's params on a governing transition row, or None."""
    if row is None:
        return None
    for rule in row.rules or []:
        if rule.get("check") == TransitionCheck.REQUIRE_APPROVAL.value:
            return rule.get("params") or {}
    return None


async def _get_request(session: AsyncSession, request_id: uuid.UUID) -> ApprovalRequest:
    request = await session.get(ApprovalRequest, request_id)
    if request is None:
        raise NotFoundError(ApprovalEntity.REQUEST, request_id)
    return request


async def _request_project(
    session: AsyncSession, request: ApprovalRequest
) -> Project:
    item = await items_service.require_item(session, request.item_id)
    return await projects_service.get_project(session, item.project_id)


async def _entry_electorates(
    session: AsyncSession, entries: Sequence[dict]
) -> list[tuple[dict, set[uuid.UUID]]]:
    """Each snapshot entry with its CURRENT electorate: a user entry is that
    one person; a team entry is the team's live members (a deleted team = an
    empty, unsatisfiable electorate)."""
    team_ids = [
        uuid.UUID(str(entry["id"]))
        for entry in entries
        if entry.get("kind") == ApproverKind.TEAM.value
    ]
    members_by_team: dict[uuid.UUID, set[uuid.UUID]] = {}
    if team_ids:
        teams = await teams_service.teams_by_ids(session, team_ids)  # deleted teams drop out
        for team in teams.values():
            members = await teams_service.list_team_members(session, team.id)
            members_by_team[team.id] = {member.id for member in members}
    resolved: list[tuple[dict, set[uuid.UUID]]] = []
    for entry in entries:
        entry_id = uuid.UUID(str(entry["id"]))
        if entry.get("kind") == ApproverKind.TEAM.value:
            resolved.append((entry, members_by_team.get(entry_id, set())))
        else:
            resolved.append((entry, {entry_id}))
    return resolved


def _entry_required(entry: dict) -> int:
    return int(entry.get("required") or 1) if entry.get("kind") == ApproverKind.TEAM.value else 1


def _entry_approved(
    entry: dict, electorate: set[uuid.UUID], votes: Sequence[ApprovalVote]
) -> int:
    """Approve verdicts from the entry's CURRENT electorate (a voter whose team
    membership was since revoked no longer counts)."""
    return sum(
        1
        for vote in votes
        if vote.verdict == ApprovalVerdict.APPROVE.value and vote.user_id in electorate
    )


def _satisfied(
    electorates: Sequence[tuple[dict, set[uuid.UUID]]], votes: Sequence[ApprovalVote]
) -> bool:
    """A request approves only when EVERY entry is satisfied."""
    if not electorates:
        return False
    return all(
        _entry_approved(entry, electorate, votes) >= _entry_required(entry)
        for entry, electorate in electorates
    )


async def _eligible_user_ids(
    session: AsyncSession, request: ApprovalRequest
) -> set[uuid.UUID]:
    """The overall electorate (vote gate + notify fan-out): the union of every
    entry's electorate."""
    eligible: set[uuid.UUID] = set()
    for _, electorate in await _entry_electorates(session, request.approvers or []):
        eligible.update(electorate)
    return eligible


def _approved_count(
    votes: Sequence[ApprovalVote], eligible: set[uuid.UUID]
) -> int:
    """Approve verdicts from CURRENTLY-eligible voters — the coarse total shown
    beside the per-entry progress."""
    return sum(
        1
        for vote in votes
        if vote.verdict == ApprovalVerdict.APPROVE.value and vote.user_id in eligible
    )


def _approvers_summary(entries: Sequence[dict]) -> str:
    """Human summary of the entry rules — event payloads + notifications
    ("Hussein Jarrar; 2 of DevOps")."""
    parts: list[str] = []
    for entry in entries:
        name = entry.get("name") or str(entry.get("id"))
        if entry.get("kind") == ApproverKind.TEAM.value:
            parts.append(f"{_entry_required(entry)} of {name}")
        else:
            parts.append(str(name))
    return "; ".join(parts)


async def _votes_for(
    session: AsyncSession, request_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[ApprovalVote]]:
    if not request_ids:
        return {}
    result = await session.execute(
        select(ApprovalVote)
        .where(ApprovalVote.request_id.in_(list(request_ids)))
        .order_by(ApprovalVote.created_at)
    )
    votes: dict[uuid.UUID, list[ApprovalVote]] = {}
    for vote in result.scalars():
        votes.setdefault(vote.request_id, []).append(vote)
    return votes


async def _reads(
    session: AsyncSession, requests: Sequence[ApprovalRequest]
) -> list[ApprovalRequestRead]:
    """Batch-hydrate requests: votes, state names, per-entry progress, the
    resolved electorate."""
    if not requests:
        return []
    votes_by_request = await _votes_for(session, [r.id for r in requests])
    states = await workflow.states_by_ids(session, {r.to_state_id for r in requests})
    electorates_by_request = {
        r.id: await _entry_electorates(session, r.approvers or []) for r in requests
    }
    user_ids: set[uuid.UUID] = {r.requested_by for r in requests if r.requested_by}
    user_ids.update(v.user_id for votes in votes_by_request.values() for v in votes)
    for electorates in electorates_by_request.values():
        for _, electorate in electorates:
            user_ids.update(electorate)
    users = await auth.users_by_ids(session, user_ids)

    def ref(user_id: uuid.UUID | None) -> ApprovalUserRef | None:
        user = users.get(user_id) if user_id else None
        return ApprovalUserRef(id=user.id, name=user.name) if user else None

    reads: list[ApprovalRequestRead] = []
    for request in requests:
        votes = votes_by_request.get(request.id, [])
        electorates = electorates_by_request[request.id]
        eligible: set[uuid.UUID] = set()
        for _, electorate in electorates:
            eligible.update(electorate)
        state = states.get(request.to_state_id)
        approvers = sorted(
            (users[uid] for uid in eligible if uid in users), key=lambda u: u.name
        )
        entries = [
            ApprovalEntryRead(
                kind=str(entry.get("kind")),
                id=uuid.UUID(str(entry["id"])),
                name=str(entry.get("name") or "?"),
                required=_entry_required(entry),
                approved_count=_entry_approved(entry, electorate, votes),
                satisfied=_entry_approved(entry, electorate, votes)
                >= _entry_required(entry),
            )
            for entry, electorate in electorates
        ]
        reads.append(
            ApprovalRequestRead(
                id=request.id,
                item_id=request.item_id,
                to_state_id=request.to_state_id,
                to_state_name=state.name if state else "?",
                status=ApprovalStatus(request.status),
                note=request.note,
                requested_by=ref(request.requested_by),
                entries=entries,
                approvers=[ApprovalUserRef(id=u.id, name=u.name) for u in approvers],
                approved_count=_approved_count(votes, eligible),
                votes=[
                    ApprovalVoteRead(
                        user=voter_ref,
                        verdict=ApprovalVerdict(vote.verdict),
                        note=vote.note,
                        created_at=vote.created_at,
                    )
                    for vote in votes
                    if (voter_ref := ref(vote.user_id)) is not None
                ],
                created_at=request.created_at,
            )
        )
    return reads


async def _emit(
    session: AsyncSession,
    event_type: ApprovalEvent,
    request: ApprovalRequest,
    project: Project,
    actor: User,
    *,
    approved_count: int,
    verdict: str | None = None,
    extra: dict | None = None,
) -> None:
    """Entity ITEM (csat/sla precedent) so the event lands in the item's History
    feed, realtime item invalidation, and item-scoped automations."""
    state = await workflow.get_state(session, request.to_state_id)
    requester = None
    if request.requested_by is not None:
        requester = (await auth.users_by_ids(session, {request.requested_by})).get(
            request.requested_by
        )
    payload: dict = {
        "item_id": str(request.item_id),
        "to_state": state.name,
        "requester": (
            {"id": str(requester.id), "name": requester.name} if requester else None
        ),
        "approved_count": approved_count,
        # Spec 107: the human summary of the per-entry rules — notifications
        # render it verbatim ("Hussein Jarrar; 2 of DevOps").
        "approvers_summary": _approvers_summary(request.approvers or []),
    }
    if verdict is not None:
        payload["voter"] = {"id": str(actor.id), "name": actor.name}
        payload["verdict"] = verdict
    payload.update(extra or {})
    await events.emit(
        session,
        event_type=event_type,
        entity_type=ItemEntity.ITEM,
        entity_id=request.item_id,
        actor_id=actor.id,
        payload=payload,
    )


# --- lifecycle ---


async def _live_request(
    session: AsyncSession, item_id: uuid.UUID, to_state_id: uuid.UUID
) -> ApprovalRequest | None:
    return await session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.item_id == item_id,
            ApprovalRequest.to_state_id == to_state_id,
            ApprovalRequest.status.in_(_LIVE),
        )
    )


async def create_request(
    session: AsyncSession, item_id: uuid.UUID, data: ApprovalRequestCreate, actor: User
) -> ApprovalRequestRead:
    item = await items_service.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, actor, Permission.ITEM_UPDATE, project=project)
    state = await workflow.get_state(session, data.to_state_id)
    if state.project_id != project.id:
        raise ConflictError(
            ApprovalEntity.REQUEST, reason=f"state {state.name} belongs to another project"
        )
    if state.id == item.state_id:
        raise ConflictError(ApprovalEntity.REQUEST, reason="the item is already in that state")
    # A request is meaningful whenever a rule gates the move — the enforcement
    # MODE is deliberately not consulted here. Resolution is ITEM-AWARE since
    # spec 107's applies_when: the governing row is first-match for THIS item.
    row = await workflow_transitions.governing_row_for(session, project, item, state.id)
    params = _approval_params(row)
    if params is None:
        raise ConflictError(
            ApprovalEntity.REQUEST,
            reason=f'no approval rule gates the move to "{state.name}"',
        )
    if await _live_request(session, item.id, state.id) is not None:
        raise ConflictError(
            ApprovalEntity.REQUEST,
            reason=f'an approval request for "{state.name}" is already open',
        )
    request = ApprovalRequest(
        item_id=item.id,
        transition_id=row.id if row else None,
        # Snapshot the rule's entries verbatim — [{kind, id, name, required?}],
        # server-normalized at rule write time (spec 107).
        approvers=list(params.get("approvers") or []),
        to_state_id=state.id,
        requested_by=actor.id,
        note=data.note,
        status=ApprovalStatus.PENDING.value,
    )
    session.add(request)
    await session.flush()
    eligible = await _eligible_user_ids(session, request)
    await _emit(
        session,
        ApprovalEvent.REQUESTED,
        request,
        project,
        actor,
        approved_count=0,
        # The notify consumer fans approval.requested out to these ids without
        # importing this module (wire-string idiom, notify loads earlier).
        extra={"eligible_user_ids": sorted(str(uid) for uid in eligible)},
    )
    return (await _reads(session, [request]))[0]


async def item_approvals(
    session: AsyncSession, item_id: uuid.UUID, actor: User
) -> ItemApprovalsRead:
    item = await items_service.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, actor, Permission.ITEM_READ, project=project)
    requests = list(
        (
            await session.execute(
                select(ApprovalRequest)
                .where(ApprovalRequest.item_id == item_id)
                .order_by(ApprovalRequest.created_at.desc())
            )
        ).scalars()
    )
    reads = await _reads(session, requests)
    live = [read for read in reads if read.status in LIVE_STATUSES]
    history = [read for read in reads if read.status not in LIVE_STATUSES]
    live_targets = {read.to_state_id for read in live}
    rows = await workflow_transitions.list_transitions(session, project.id)
    # Item-aware resolution (spec 107 applies_when): one union snapshot, then
    # pure first-match per target — a rule scoped to other issue types never
    # offers "Request approval" here.
    snapshot = await workflow_transitions.snapshot_for(session, project, item, rows)
    requestable: list[RequestableState] = []
    for state in await workflow.list_states(session, project.id):
        if state.id == item.state_id or state.id in live_targets:
            continue
        candidates = workflow_transitions.edge_candidates(rows, item.state_id, state.id)
        row = workflow_transitions.governing_row(candidates, snapshot) if candidates else None
        if _approval_params(row) is not None:
            requestable.append(RequestableState(state_id=state.id, name=state.name))
    return ItemApprovalsRead(live=live, history=history, requestable_to_states=requestable)


async def vote(
    session: AsyncSession, request_id: uuid.UUID, data: ApprovalVoteCreate, actor: User
) -> VoteResult:
    request = await _get_request(session, request_id)
    project = await _request_project(session, request)
    if request.status != ApprovalStatus.PENDING.value:
        raise ConflictError(
            ApprovalEntity.REQUEST, reason=f"request is {request.status}, not pending"
        )
    electorates = await _entry_electorates(session, request.approvers or [])
    eligible: set[uuid.UUID] = set()
    for _, electorate in electorates:
        eligible.update(electorate)
    if actor.id not in eligible:
        raise ForbiddenError("you are not an approver on this request")
    existing = await session.scalar(
        select(ApprovalVote).where(
            ApprovalVote.request_id == request.id, ApprovalVote.user_id == actor.id
        )
    )
    if existing is None:
        session.add(
            ApprovalVote(
                request_id=request.id,
                user_id=actor.id,
                verdict=data.verdict.value,
                note=data.note,
            )
        )
    else:  # revote while pending REPLACES the earlier verdict
        existing.verdict = data.verdict.value
        existing.note = data.note
    await session.flush()
    votes = list(
        (
            await session.execute(
                select(ApprovalVote).where(ApprovalVote.request_id == request.id)
            )
        ).scalars()
    )
    approved_count = _approved_count(votes, eligible)
    await _emit(
        session,
        ApprovalEvent.VOTED,
        request,
        project,
        actor,
        approved_count=approved_count,
        verdict=data.verdict.value,
    )
    applied = False
    errors: list[str] = []
    if data.verdict is ApprovalVerdict.DECLINE:
        request.status = ApprovalStatus.DECLINED.value
        await session.flush()
        await _emit(
            session,
            ApprovalEvent.DECLINED,
            request,
            project,
            actor,
            approved_count=approved_count,
            verdict=data.verdict.value,
        )
    elif _satisfied(electorates, votes):
        request.status = ApprovalStatus.APPROVED.value
        await session.flush()
        await _emit(
            session,
            ApprovalEvent.APPROVED,
            request,
            project,
            actor,
            approved_count=approved_count,
            verdict=data.verdict.value,
        )
        applied, errors = await _auto_apply(session, request, actor)
    return VoteResult(
        request=(await _reads(session, [request]))[0], applied=applied, errors=errors
    )


async def _auto_apply(
    session: AsyncSession, request: ApprovalRequest, actor: User
) -> tuple[bool, list[str]]:
    """Spec 71 §4: the deciding vote applies the transition itself, acting AS THE
    FINAL APPROVER (real actor for audit). The other guards re-run inside
    update_item; a failure rolls the savepoint back and BANKS the unlock — the
    request stays `approved`, the errors ride the vote response so the UI can
    toast them, and anyone can complete the move later (which consumes it)."""
    try:
        async with session.begin_nested():
            await items_service.update_item(
                session, request.item_id, ItemUpdate(state_id=request.to_state_id), actor
            )
    except TransitionError as exc:
        return False, exc.errors
    except ForbiddenError as exc:
        # The final approver may not hold item.update — the unlock banks the same way.
        return False, [str(exc)]
    return True, []


async def cancel_request(
    session: AsyncSession, request_id: uuid.UUID, actor: User
) -> None:
    request = await _get_request(session, request_id)
    project = await _request_project(session, request)
    if request.status not in _LIVE:
        raise ConflictError(
            ApprovalEntity.REQUEST, reason=f"request is {request.status} — nothing to cancel"
        )
    if request.requested_by != actor.id:
        await authz.require(session, actor, Permission.PROJECT_MANAGE, project=project)
    eligible = await _eligible_user_ids(session, request)
    votes = (await _votes_for(session, [request.id])).get(request.id, [])
    request.status = ApprovalStatus.CANCELED.value
    await session.flush()
    await _emit(
        session,
        ApprovalEvent.CANCELED,
        request,
        project,
        actor,
        approved_count=_approved_count(votes, eligible),
    )


async def pending_for_user(
    session: AsyncSession, actor: User
) -> list[PendingApprovalRead]:
    """MY approval queue: pending requests where I'm eligible (snapshot users or
    live team membership) — powers the My Work card. Approvers are explicitly
    named, so no extra RBAC filter on the key/title display."""
    requests = list(
        (
            await session.execute(
                select(ApprovalRequest)
                .where(ApprovalRequest.status == ApprovalStatus.PENDING.value)
                .order_by(ApprovalRequest.created_at.desc())
            )
        ).scalars()
    )
    items_by_id = await items_service.items_by_ids(session, {r.item_id for r in requests})
    my_team_ids = await teams_service.user_team_ids(session, actor.id)  # teams are global (spec 86)
    mine: list[ApprovalRequest] = []
    for request in requests:
        item = items_by_id.get(request.item_id)
        if item is None:
            continue
        for entry in request.approvers or []:
            entry_id = uuid.UUID(str(entry.get("id")))
            if entry.get("kind") == ApproverKind.TEAM.value:
                if entry_id in my_team_ids:
                    mine.append(request)
                    break
            elif entry_id == actor.id:
                mine.append(request)
                break
    if not mine:
        return []
    keys = await projects_service.project_keys(
        session, {items_by_id[r.item_id].project_id for r in mine}
    )
    states = await workflow.states_by_ids(session, {r.to_state_id for r in mine})
    users = await auth.users_by_ids(
        session, {r.requested_by for r in mine if r.requested_by}
    )
    rows: list[PendingApprovalRead] = []
    for request in mine:
        item = items_by_id[request.item_id]
        state = states.get(request.to_state_id)
        requester = users.get(request.requested_by) if request.requested_by else None
        rows.append(
            PendingApprovalRead(
                id=request.id,
                item_id=item.id,
                item_key=f"{keys[item.project_id]}-{item.number}",
                item_title=item.title,
                to_state_name=state.name if state else "?",
                requested_by=(
                    ApprovalUserRef(id=requester.id, name=requester.name)
                    if requester
                    else None
                ),
                note=request.note,
                created_at=request.created_at,
            )
        )
    return rows
