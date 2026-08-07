"""Approvals on workflow transitions (spec 71; per-entry rules since spec 107):
guard seam, per-entry satisfaction (a user approves personally, a team needs N
of its CURRENT members), auto-apply as the final approver, banked unlocks, and
rule write-validation.

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.approvals import service as approvals
from radd.modules.approvals.models import ApprovalRequest
from radd.modules.approvals.schemas import ApprovalRequestCreate, ApprovalVoteCreate
from radd.modules.approvals.types import ApprovalStatus, ApprovalVerdict
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.events import service as events
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
from radd.modules.workflow import service as workflow, transitions
from radd.modules.workflow.guards import TransitionError
from radd.modules.workflow.schemas import TransitionCreate, TransitionRule
from radd.modules.workflow.types import TransitionCheck, TransitionMode
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def actor(db) -> User:
    user = User(
        email=f"apr-{uuid.uuid4().hex[:8]}@example.com",
        name="Approval Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _member(db, name: str, project=None) -> User:
    """An active user (holds the global member floor); with `project`, also a
    direct project member (the builtin member role) so auto-apply's item.update
    check can pass."""
    user = User(
        email=f"apr-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    if project is not None:
        # These tests don't boot the app, so the startup-seeded builtin roles
        # aren't there on a fresh database — ensure them (idempotent).
        await auth_roles.ensure_builtin_roles(db)
        role = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
        db.add(GlobalRoleGrant(project_id=project.id, user_id=user.id, role_id=role.id))
    await db.flush()
    return user


async def _project_with_states(db):
    project = await projects_service.create_project(
        db,
        ProjectCreate(key=f"AP{uuid.uuid4().hex[:4].upper()}", name="P"),
    )
    await settings_service.set_value(
        db,
        SettingKey.WORKFLOW_TRANSITION_MODE,
        SettingScope.PROJECT,
        project.id,
        TransitionMode.GUARDS.value,
    )
    states = {s.name: s for s in await workflow.list_states(db, project.id)}
    return project, states


def user_entry(user: User) -> dict:
    return {"kind": "user", "id": str(user.id)}


def team_entry(team, required: int = 1) -> dict:
    return {"kind": "team", "id": str(team.id), "required": required}


def approval_rule(*entries: dict) -> TransitionRule:
    return TransitionRule(
        check=TransitionCheck.REQUIRE_APPROVAL, params={"approvers": list(entries)}
    )


async def _expect_blocked(db, item_id, data, actor) -> TransitionError:
    """Run an update that must raise TransitionError inside a SAVEPOINT and roll
    it back (test_transitions.py idiom)."""
    savepoint = await db.begin_nested()
    with pytest.raises(TransitionError) as exc:
        await items.update_item(db, item_id, data, actor)
    await savepoint.rollback()
    return exc.value


# --- (a) guard seam + consume-on-use ---


async def test_guard_blocks_then_approved_request_unlocks_one_move(db, actor):
    project, states = await _project_with_states(db)
    approver = await _member(db, "Approver A")
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            from_state_id=states["Triage"].id,
            to_state_id=states["In Progress"].id,
            rules=[approval_rule(user_entry(approver))],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)

    error = await _expect_blocked(
        db, item.id, ItemUpdate(state_id=states["In Progress"].id), actor
    )
    # The failure names the entry rules (spec 107), not a bare count.
    assert error.errors == ["approval required (Approver A)"]

    read = await approvals.create_request(
        db, item.id, ApprovalRequestCreate(to_state_id=states["In Progress"].id), actor
    )
    # A second live request for the same target 409s.
    with pytest.raises(ConflictError):
        await approvals.create_request(
            db, item.id, ApprovalRequestCreate(to_state_id=states["In Progress"].id), actor
        )
    # Still blocked while merely PENDING.
    await _expect_blocked(db, item.id, ItemUpdate(state_id=states["In Progress"].id), actor)

    # Bank the unlock directly (the vote path is exercised below) — the guard
    # seam only looks at status=approved.
    request = await db.get(ApprovalRequest, read.id)
    request.status = ApprovalStatus.APPROVED.value
    await db.flush()
    assert await approvals.approved_target_state_ids(db, item.id) == {
        str(states["In Progress"].id)
    }

    moved = await items.update_item(
        db, item.id, ItemUpdate(state_id=states["In Progress"].id), actor
    )
    assert moved.state.name == "In Progress"
    assert request.status == ApprovalStatus.APPLIED.value  # consumed on use

    # One approval unlocks ONE move: back to Triage, the gate is armed again.
    await items.update_item(db, item.id, ItemUpdate(state_id=states["Triage"].id), actor)
    await _expect_blocked(db, item.id, ItemUpdate(state_id=states["In Progress"].id), actor)


# --- (b) per-entry satisfaction, auto-apply, decline, live team eligibility ---


async def test_team_two_of_three_approves_auto_apply_as_final_approver(db, actor):
    project, states = await _project_with_states(db)
    a1 = await _member(db, "Approver One", project)
    a2 = await _member(db, "Approver Two", project)
    a3 = await _member(db, "Approver Three", project)
    outsider = await _member(db, "Not An Approver")
    team = await teams_service.create_team(
        db, TeamCreate(name=f"Approvers {uuid.uuid4().hex[:4]}")
    )
    for member in (a1, a2, a3):
        await teams_service.add_team_member(db, team.id, member.id)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["Done"].id,  # wildcard from
            rules=[approval_rule(team_entry(team, required=2))],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    read = await approvals.create_request(
        db, item.id, ApprovalRequestCreate(to_state_id=states["Done"].id), actor
    )
    assert {a.id for a in read.approvers} == {a1.id, a2.id, a3.id}
    assert [(e.kind, e.required, e.approved_count, e.satisfied) for e in read.entries] == [
        ("team", 2, 0, False)
    ]

    with pytest.raises(ForbiddenError):
        await approvals.vote(
            db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), outsider
        )

    first = await approvals.vote(
        db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), a1
    )
    assert not first.applied and first.request.status is ApprovalStatus.PENDING
    assert first.request.entries[0].approved_count == 1
    assert not first.request.entries[0].satisfied

    second = await approvals.vote(
        db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), a2
    )
    assert second.applied and second.errors == []
    assert second.request.status is ApprovalStatus.APPLIED  # auto-applied + consumed
    assert second.request.entries[0].satisfied
    assert (await items.get_item(db, item.id, actor)).state.name == "Done"
    # The move is attributed to the FINAL APPROVER (real actor for audit).
    updated = await events.query_events(
        db, entity_type="item", entity_id=str(item.id), event_types=["item.updated"], limit=1
    )
    assert updated[0].actor_id == a2.id

    # No further votes on a settled request.
    with pytest.raises(ConflictError):
        await approvals.vote(
            db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), a3
        )


async def test_every_user_entry_must_approve_personally(db, actor):
    """Spec 107: two user entries AND together — one enthusiastic approver can
    no longer clear a colleague's bar."""
    project, states = await _project_with_states(db)
    a1 = await _member(db, "Approver One", project)
    a2 = await _member(db, "Approver Two", project)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["Done"].id,
            rules=[approval_rule(user_entry(a1), user_entry(a2))],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    read = await approvals.create_request(
        db, item.id, ApprovalRequestCreate(to_state_id=states["Done"].id), actor
    )
    first = await approvals.vote(
        db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), a1
    )
    assert first.request.status is ApprovalStatus.PENDING
    assert [e.satisfied for e in first.request.entries] == [True, False]
    second = await approvals.vote(
        db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), a2
    )
    assert second.applied
    assert (await items.get_item(db, item.id, actor)).state.name == "Done"


async def test_mixed_entries_user_and_team(db, actor):
    project, states = await _project_with_states(db)
    lead = await _member(db, "The Lead", project)
    t1 = await _member(db, "Team Member One", project)
    t2 = await _member(db, "Team Member Two", project)
    team = await teams_service.create_team(
        db, TeamCreate(name=f"Reviewers {uuid.uuid4().hex[:4]}")
    )
    for member in (t1, t2):
        await teams_service.add_team_member(db, team.id, member.id)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["Done"].id,
            rules=[approval_rule(user_entry(lead), team_entry(team, required=2))],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    read = await approvals.create_request(
        db, item.id, ApprovalRequestCreate(to_state_id=states["Done"].id), actor
    )
    # Both team members approve — still pending: the lead hasn't.
    await approvals.vote(db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), t1)
    partial = await approvals.vote(
        db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), t2
    )
    assert partial.request.status is ApprovalStatus.PENDING
    assert [e.satisfied for e in partial.request.entries] == [False, True]
    final = await approvals.vote(
        db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), lead
    )
    assert final.applied


async def test_any_decline_settles_the_request(db, actor):
    project, states = await _project_with_states(db)
    a1 = await _member(db, "Approver One", project)
    a2 = await _member(db, "Approver Two", project)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["Done"].id,
            rules=[approval_rule(user_entry(a1), user_entry(a2))],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    read = await approvals.create_request(
        db, item.id, ApprovalRequestCreate(to_state_id=states["Done"].id), actor
    )
    await approvals.vote(db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), a1)
    declined = await approvals.vote(
        db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.DECLINE, note="not yet"), a2
    )
    assert declined.request.status is ApprovalStatus.DECLINED and not declined.applied
    # Declined is terminal for the request — but a NEW request can be raised.
    fresh = await approvals.create_request(
        db, item.id, ApprovalRequestCreate(to_state_id=states["Done"].id), actor
    )
    assert fresh.status is ApprovalStatus.PENDING


async def test_team_eligibility_resolves_live(db, actor):
    project, states = await _project_with_states(db)
    team = await teams_service.create_team(
        db, TeamCreate(name=f"Approvers {uuid.uuid4().hex[:4]}")
    )
    late_joiner = await _member(db, "Late Joiner", project)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["Done"].id,
            rules=[approval_rule(team_entry(team))],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    read = await approvals.create_request(
        db, item.id, ApprovalRequestCreate(to_state_id=states["Done"].id), actor
    )
    # Not a member yet -> not eligible.
    with pytest.raises(ForbiddenError):
        await approvals.vote(
            db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), late_joiner
        )
    # Team membership is the LIVE part of the electorate (spec 71).
    await teams_service.add_team_member(db, team.id, late_joiner.id)
    result = await approvals.vote(
        db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), late_joiner
    )
    assert result.applied
    assert (await items.get_item(db, item.id, actor)).state.name == "Done"


# --- (c) rule write-validation ---


async def test_rule_write_validation_conflicts(db, actor):
    project, states = await _project_with_states(db)
    approver = await _member(db, "Approver A")

    def create(entries):
        return transitions.create_transition(
            db,
            TransitionCreate(
                project_id=project.id,
                to_state_id=states["Done"].id,
                rules=[
                    TransitionRule(
                        check=TransitionCheck.REQUIRE_APPROVAL,
                        params={"approvers": entries},
                    )
                ],
            ),
        )

    with pytest.raises(ConflictError):  # unknown user
        await create([{"kind": "user", "id": str(uuid.uuid4())}])
    with pytest.raises(ConflictError):  # unknown team
        await create([{"kind": "team", "id": str(uuid.uuid4()), "required": 1}])
    with pytest.raises(ConflictError):  # required < 1 on a team entry
        await create([{"kind": "team", "id": str(uuid.uuid4()), "required": 0}])
    with pytest.raises(ConflictError):  # no entries at all
        await create([])
    with pytest.raises(ConflictError):  # duplicate entry
        await create([user_entry(approver), user_entry(approver)])
    # A valid rule writes fine.
    await create([user_entry(approver)])


# --- (d) banked unlock: other guards still apply after approval ---


async def test_banked_unlock_when_other_guards_still_fail(db, actor):
    project, states = await _project_with_states(db)
    approver = await _member(db, "Approver A", project)
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            from_state_id=states["Triage"].id,
            to_state_id=states["In Progress"].id,
            rules=[
                TransitionRule(
                    check=TransitionCheck.REQUIRE_FIELD,
                    params={"kind": "builtin", "key": "assignee", "op": "set"},
                ),
                approval_rule(user_entry(approver)),
            ],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    read = await approvals.create_request(
        db, item.id, ApprovalRequestCreate(to_state_id=states["In Progress"].id), actor
    )
    result = await approvals.vote(
        db, read.id, ApprovalVoteCreate(verdict=ApprovalVerdict.APPROVE), approver
    )
    # Approved, but the assignee guard blocked the auto-apply — unlock BANKED,
    # the guard errors surface on the vote response for the UI toast.
    assert not result.applied
    assert result.errors == ["an assignee is required"]
    assert result.request.status is ApprovalStatus.APPROVED
    assert (await items.get_item(db, item.id, actor)).state.name == "Triage"

    # Fix the other guard, then anyone completes the move — which consumes it.
    await items.update_item(db, item.id, ItemUpdate(assignee_id=actor.id), actor)
    moved = await items.update_item(
        db, item.id, ItemUpdate(state_id=states["In Progress"].id), actor
    )
    assert moved.state.name == "In Progress"
    request = await db.get(ApprovalRequest, read.id)
    assert request.status == ApprovalStatus.APPLIED.value


# --- applies_when scoping (spec 107 follow-up) ---


async def test_requestable_respects_applies_when(db, actor):
    """An approval rule scoped to blockers never offers "Request approval" on —
    or accepts a request for — a normal-priority item."""
    project, states = await _project_with_states(db)
    approver = await _member(db, "Approver A")
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["Done"].id,
            applies_when=[
                {"kind": "builtin", "key": "priority", "op": "is", "values": ["blocker"]}
            ],
            rules=[approval_rule(user_entry(approver))],
        ),
    )
    normal = await items.create_item(db, ItemCreate(project_id=project.id, title="n"), actor)
    blocker = await items.create_item(
        db, ItemCreate(project_id=project.id, title="b", priority="blocker"), actor
    )
    assert (await approvals.item_approvals(db, normal.id, actor)).requestable_to_states == []
    with pytest.raises(ConflictError):
        await approvals.create_request(
            db, normal.id, ApprovalRequestCreate(to_state_id=states["Done"].id), actor
        )
    blocker_view = await approvals.item_approvals(db, blocker.id, actor)
    assert [s.name for s in blocker_view.requestable_to_states] == ["Done"]


# --- cancel + pending queue ---


async def test_cancel_and_pending_queue(db, actor):
    project, states = await _project_with_states(db)
    approver = await _member(db, "Approver A")
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["Done"].id,
            rules=[approval_rule(user_entry(approver))],
        ),
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    read = await approvals.create_request(
        db, item.id, ApprovalRequestCreate(to_state_id=states["Done"].id), actor
    )

    pending = await approvals.pending_for_user(db, approver)
    assert [p.id for p in pending] == [read.id]
    assert pending[0].to_state_name == "Done" and pending[0].item_title == "i"
    # The requester isn't an approver — their queue is empty.
    assert await approvals.pending_for_user(db, actor) == []

    # A non-requester non-manager cannot cancel.
    with pytest.raises(ForbiddenError):
        await approvals.cancel_request(db, read.id, approver)
    await approvals.cancel_request(db, read.id, actor)  # the requester can
    request = await db.get(ApprovalRequest, read.id)
    assert request.status == ApprovalStatus.CANCELED.value
    assert await approvals.pending_for_user(db, approver) == []

    # The rail's requestable list offers the gated target again post-cancel.
    item_view = await approvals.item_approvals(db, item.id, actor)
    assert item_view.live == []
    assert [r.status for r in item_view.history] == [ApprovalStatus.CANCELED]
    assert [s.name for s in item_view.requestable_to_states] == ["Done"]
