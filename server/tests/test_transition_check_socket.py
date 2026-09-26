"""Approval gates ride the kernel TRANSITION_CHECK socket the optional approvals
plugin contributes (RADD-1383; an `except ImportError` guard never fires).
Withdrawn: a stored require_approval rule FAILS CLOSED even with an approval
banked, a new one cannot be written, the row's other rules stay editable.
Registered: the banked approval unlocks exactly ONE move.
"""

import uuid

import pytest

from radd.exceptions import ConflictError
from radd.kernel.registry import registries
from radd.kernel.sockets import Socket
from radd.modules.approvals import plugin as approvals_plugin, service as approvals
from radd.modules.approvals.models import ApprovalRequest
from radd.modules.approvals.schemas import ApprovalRequestCreate
from radd.modules.approvals.types import ApprovalCheck, ApprovalStatus
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.workflow import service as workflow, transitions
from radd.modules.workflow.guards import TransitionError, unprovided_failure
from radd.modules.workflow.schemas import TransitionCreate, TransitionRule, TransitionUpdate
from radd.modules.workflow.types import TransitionCheck, TransitionMode

from _factories import make_user

CLOSED = unprovided_failure(ApprovalCheck.REQUIRE_APPROVAL.value)


@pytest.fixture
async def actor(db) -> User:
    return await make_user(db, role=InstanceRole.ADMIN, name="Gate Keeper")


def approval(user: User) -> TransitionRule:
    return TransitionRule(
        check=ApprovalCheck.REQUIRE_APPROVAL,
        params={"approvers": [{"kind": "user", "id": str(user.id)}]},
    )


async def _blocked(db, item_id, state_id, actor) -> list[str]:
    savepoint = await db.begin_nested()
    with pytest.raises(TransitionError) as exc:
        await items.update_item(db, item_id, ItemUpdate(state_id=state_id), actor)
    await savepoint.rollback()
    return exc.value.errors


async def test_withdrawn_approvals_fail_closed_and_registered_unlock_one_move(db, actor):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"GT{uuid.uuid4().hex[:4].upper()}", name="Gates")
    )
    await settings_service.set_value(
        db, SettingKey.WORKFLOW_TRANSITION_MODE, SettingScope.PROJECT, project.id,
        TransitionMode.GUARDS.value,
    )
    states = {s.name: s for s in await workflow.list_states(db, project.id)}
    triage, done = states["Triage"].id, states["Done"].id
    row = await transitions.create_transition(
        db, TransitionCreate(project_id=project.id, to_state_id=done, rules=[approval(actor)])
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="gated"), actor)
    request = await approvals.create_request(
        db, item.id, ApprovalRequestCreate(to_state_id=done), actor
    )
    # Bank the unlock BEFORE the withdrawal: a disabled plugin must not honour it.
    banked = await db.get(ApprovalRequest, request.id)
    banked.status = ApprovalStatus.APPROVED.value
    await db.flush()

    registries.unregister_plugin(approvals_plugin)
    try:
        assert registries.providers(Socket.TRANSITION_CHECK) == {}
        assert await _blocked(db, item.id, done, actor) == [CLOSED]
        row_item = await items.require_item(db, item.id)
        targets = await transitions.allowed_transitions(db, project, row_item)
        assert {t.state_id: t.failures for t in targets.targets}[done] == [CLOSED]
        # No provider validates a NEW rule, so none is written…
        with pytest.raises(ConflictError):
            await transitions.create_transition(
                db, TransitionCreate(project_id=project.id, to_state_id=triage, rules=[approval(actor)])
            )
        # …but the row's other rules stay editable with the stored gate kept as is.
        kept = TransitionRule(**row.rules[0])
        field = TransitionRule(
            check=TransitionCheck.REQUIRE_FIELD,
            params={"kind": "builtin", "key": "assignee", "op": "set"},
        )
        await transitions.update_transition(db, row.id, TransitionUpdate(rules=[field, kept]))
        await items.update_item(db, item.id, ItemUpdate(assignee_id=actor.id), actor)
        assert await _blocked(db, item.id, done, actor) == [CLOSED]
        assert banked.status == ApprovalStatus.APPROVED.value  # nothing consumed it
    finally:
        registries.register_plugin(approvals_plugin)

    moved = await items.update_item(db, item.id, ItemUpdate(state_id=done), actor)
    assert moved.state.name == "Done"
    assert banked.status == ApprovalStatus.APPLIED.value  # spent by that move
    await items.update_item(db, item.id, ItemUpdate(state_id=triage), actor)
    assert await _blocked(db, item.id, done, actor) == ["approval required (Gate Keeper)"]
