"""Bulk operations (spec 68): skip-and-report batch edit + cross-project move.

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist.
"""

import uuid
from datetime import date


from radd.modules.auth import authz, roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.cycles import service as cycles_service
from radd.modules.cycles.schemas import CycleCreate
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldType
from radd.modules.items import bulk, service as items
from radd.modules.items.enums import BulkSkipReason, ItemKind
from radd.modules.items.schemas import (
    ItemBulkMove,
    ItemBulkPatch,
    ItemBulkUpdate,
    ItemCreate,
)
from radd.modules.releases import service as releases_service
from radd.modules.releases.schemas import ReleaseCreate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.workflow import service as workflow, transitions
from radd.modules.workflow.schemas import TransitionCreate, TransitionRule
from radd.modules.workflow.types import TransitionCheck, TransitionMode
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

from _factories import make_user


async def _project_with_states(db, key_prefix="BA"):
    project = await projects_service.create_project(
        db,
        ProjectCreate(
            key=f"{key_prefix}{uuid.uuid4().hex[:4].upper()}",
            name="P",
        ),
    )
    states = {s.name: s for s in await workflow.list_states(db, project.id)}
    return project, states


async def test_bulk_update_applies_and_skips(db, actor):
    project, states = await _project_with_states(db)
    await settings_service.set_value(
        db,
        SettingKey.WORKFLOW_TRANSITION_MODE,
        SettingScope.PROJECT,
        project.id,
        TransitionMode.GUARDS.value,
    )
    await transitions.create_transition(
        db,
        TransitionCreate(
            project_id=project.id,
            to_state_id=states["In Progress"].id,
            rules=[
                TransitionRule(
                    check=TransitionCheck.REQUIRE_FIELD,
                    params={"kind": "builtin", "key": "assignee", "op": "set"},
                )
            ],
        ),
    )
    blocked = await items.create_item(
        db, ItemCreate(project_id=project.id, title="no assignee"), actor
    )
    ok = await items.create_item(
        db, ItemCreate(project_id=project.id, title="assigned", assignee_id=actor.id), actor
    )
    missing = uuid.uuid4()

    result = await bulk.bulk_update_items(
        db,
        ItemBulkUpdate(
            item_ids=[blocked.id, ok.id, missing],
            patch=ItemBulkPatch(state_id=states["In Progress"].id),
        ),
        actor,
    )
    assert result.updated == [ok.id]
    reasons = {s.item_id: s.reason for s in result.skipped}
    assert reasons[blocked.id] == BulkSkipReason.TRANSITION_BLOCKED
    assert reasons[missing] == BulkSkipReason.NOT_FOUND
    # The blocked item's savepoint rolled back — state unchanged.
    assert (await items.get_item(db, blocked.id, actor)).state.name == "Triage"
    assert (await items.get_item(db, ok.id, actor)).state.name == "In Progress"


async def test_bulk_update_forbidden_and_label_deltas(db, actor):
    project, _ = await _project_with_states(db)
    item = await items.create_item(
        db,
        ItemCreate(project_id=project.id, title="labelled", labels=["keep", "drop"]),
        actor,
    )
    # An INACTIVE user (no member floor) can't update → skipped, not raised.
    inactive = User(
        email=f"bulk-out-{uuid.uuid4().hex[:8]}@example.com",
        name="Inactive",
        instance_role=InstanceRole.MEMBER.value,
        active=False,
    )
    db.add(inactive)
    await db.flush()
    result = await bulk.bulk_update_items(
        db,
        ItemBulkUpdate(item_ids=[item.id], patch=ItemBulkPatch(flagged=True)),
        inactive,
    )
    assert result.updated == [] and result.skipped[0].reason == BulkSkipReason.FORBIDDEN

    # Label DELTAS: add + remove, other labels untouched.
    result = await bulk.bulk_update_items(
        db,
        ItemBulkUpdate(
            item_ids=[item.id],
            patch=ItemBulkPatch(add_labels=["new"], remove_labels=["drop"]),
        ),
        actor,
    )
    assert result.updated == [item.id]
    read = await items.get_item(db, item.id, actor)
    assert sorted(read.labels) == ["keep", "new"]


async def test_bulk_move_rekeys_maps_and_aliases(db, actor):
    src, src_states = await _project_with_states(db, key_prefix="SRC")
    dst = await projects_service.create_project(
        db,
        ProjectCreate(key=f"DST{uuid.uuid4().hex[:4].upper()}", name="Dst"),
    )
    # A custom field that exists only in the SOURCE project's scope.
    await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[src.id],
            key="flavor",
            name="Flavor",
            type=FieldType.TEXT,
        ),
    )
    release = await releases_service.create_release(
        db, ReleaseCreate(project_id=src.id, name="R1", version="1.0")
    )
    cycle = await cycles_service.create_cycle(db, CycleCreate(name="C1"), today=date(2026, 7, 1))
    epic = await items.create_item(
        db, ItemCreate(project_id=src.id, title="epic", kind=ItemKind.EPIC), actor
    )
    child = await items.create_item(
        db,
        ItemCreate(
            project_id=src.id,
            title="child",
            parent_id=epic.id,
            state_id=src_states["In Progress"].id,
            release_id=release.id,
            cycle_id=cycle.id,
            custom_fields={"flavor": "salt"},
        ),
        actor,
    )

    # Spec 80: a move takes EXACTLY the selection — the child STAYS in the
    # source project and keeps its (now cross-project) parent link.
    result = await bulk.bulk_move_items(
        db, ItemBulkMove(item_ids=[epic.id], target_project_id=dst.id), actor
    )
    assert {m.item_id for m in result.moved} == {epic.id}
    assert result.skipped == []
    staying = await items.get_item(db, child.id, actor)
    assert staying.key.startswith("SRC")
    assert staying.parent is not None and staying.parent.id == epic.id
    assert (await items.get_item(db, epic.id, actor)).key.startswith("DST")

    # Moving the child too: re-key + name mapping, parent link survives.
    result = await bulk.bulk_move_items(
        db, ItemBulkMove(item_ids=[child.id], target_project_id=dst.id), actor
    )
    moved_child = next(m for m in result.moved if m.item_id == child.id)
    assert moved_child.dropped_fields == ["flavor"]

    read = await items.get_item(db, child.id, actor)
    assert read.key.startswith("DST")
    assert read.state.name == "In Progress"  # mapped by name
    assert read.release is None  # project-scoped → cleared
    assert read.cycle is not None and read.cycle.name == "C1"  # global → kept
    assert read.parent is not None and read.parent.id == epic.id

    # Old keys keep resolving via the alias table; response carries the NEW key.
    old = await items.get_item_by_key(db, moved_child.old_key, actor)
    assert old.id == child.id and old.key == moved_child.new_key
    raw = await items.find_item_by_key(db, moved_child.old_key)
    assert raw is not None and raw.id == child.id


async def test_bulk_move_takes_subtasks_along_and_never_alone(db, actor):
    src, _ = await _project_with_states(db, key_prefix="SBA")
    dst = await projects_service.create_project(
        db,
        ProjectCreate(key=f"SBB{uuid.uuid4().hex[:4].upper()}", name="Dst"),
    )
    epic = await items.create_item(
        db, ItemCreate(project_id=src.id, title="e", kind=ItemKind.EPIC), actor
    )
    issue = await items.create_item(
        db, ItemCreate(project_id=src.id, title="i", parent_id=epic.id), actor
    )
    subtask = await items.create_item(
        db,
        ItemCreate(project_id=src.id, title="s", kind=ItemKind.SUBTASK, parent_id=issue.id),
        actor,
    )
    # RADD-1492: a subtask selected without its issue stays, and says why.
    result = await bulk.bulk_move_items(
        db, ItemBulkMove(item_ids=[subtask.id], target_project_id=dst.id), actor
    )
    assert result.moved == []
    assert [(s.item_id, s.reason) for s in result.skipped] == [
        (subtask.id, BulkSkipReason.SUBTASK_FOLLOWS_PARENT)
    ]
    assert (await items.get_item(db, subtask.id, actor)).key.startswith("SBA")

    # An issue moved without its epic takes its subtasks along and keeps the
    # (cross-project, still legal) epic link.
    result = await bulk.bulk_move_items(
        db, ItemBulkMove(item_ids=[issue.id], target_project_id=dst.id), actor
    )
    assert [m.item_id for m in result.moved] == [issue.id, subtask.id]
    assert result.skipped == []
    read = await items.get_item(db, issue.id, actor)
    assert read.key.startswith("SBB")
    assert read.parent is not None and read.parent.id == epic.id
    step = await items.get_item(db, subtask.id, actor)
    assert step.key.startswith("SBB")
    assert step.parent is not None and step.parent.id == issue.id
    # The epic itself never moved, and moving it leaves its issues behind.
    assert (await items.get_item(db, epic.id, actor)).key.startswith("SBA")
    result = await bulk.bulk_move_items(
        db, ItemBulkMove(item_ids=[epic.id], target_project_id=dst.id), actor
    )
    assert [m.item_id for m in result.moved] == [epic.id]


async def test_bulk_update_parent_id_applies_kind_rules_and_row_gate(db, actor):
    """RADD-1474: `parent_id` in a bulk patch sets the epic of every issue in one
    call; each row still goes through `_resolve_parent`, so a subtask handed an
    epic is refused with the kind reason, a subtask cannot be cleared, and a
    parent the actor cannot read is refused — forbidden when its project is
    closed to them, missing when only the row is (RADD-1455) — all as skipped
    rows, never a failed batch."""
    project, _ = await _project_with_states(db, key_prefix="BP")
    epic = await items.create_item(
        db, ItemCreate(project_id=project.id, title="e", kind=ItemKind.EPIC), actor
    )
    issues = [
        await items.create_item(db, ItemCreate(project_id=project.id, title=f"i{n}"), actor)
        for n in range(3)
    ]
    subtask = await items.create_item(
        db,
        ItemCreate(project_id=project.id, title="s", kind=ItemKind.SUBTASK, parent_id=issues[0].id),
        actor,
    )

    result = await bulk.bulk_update_items(
        db,
        ItemBulkUpdate(
            item_ids=[*(issue.id for issue in issues), subtask.id],
            patch=ItemBulkPatch(parent_id=epic.id),
        ),
        actor,
    )
    assert result.updated == [issue.id for issue in issues]
    [skipped] = result.skipped
    assert skipped.item_id == subtask.id and skipped.reason == BulkSkipReason.INVALID_TARGET
    assert "parent must be of kind issue" in (skipped.detail or "")
    for issue in issues:
        read = await items.get_item(db, issue.id, actor)
        assert read.parent is not None and read.parent.id == epic.id
    # The subtask's savepoint rolled back: it still hangs off its issue.
    assert (await items.get_item(db, subtask.id, actor)).parent.id == issues[0].id

    # An explicit null clears an issue's epic; a subtask has nothing to clear to.
    result = await bulk.bulk_update_items(
        db,
        ItemBulkUpdate(item_ids=[issues[0].id, subtask.id], patch=ItemBulkPatch(parent_id=None)),
        actor,
    )
    assert result.updated == [issues[0].id]
    [skipped] = result.skipped
    assert skipped.reason == BulkSkipReason.INVALID_TARGET
    assert "requires a parent issue" in (skipped.detail or "")
    assert (await items.get_item(db, issues[0].id, actor)).parent is None

    # The TARGET is resolved through the read seam (RADD-1455). Two readers who
    # cannot see the epic in another project: one with no access to that project
    # at all (the project gate refuses — FORBIDDEN), one holding `item.read@own`
    # there (the project admits them, the ROW gate hides the epic — it answers as
    # missing, INVALID_TARGET). The Baseline is emptied first: its unqualified
    # `item.read` would make every project readable and both checks vacuous.
    elsewhere = await projects_service.create_project(
        db, ProjectCreate(key=f"BQ{uuid.uuid4().hex[:4].upper()}", name="Elsewhere")
    )
    hidden_epic = await items.create_item(
        db, ItemCreate(project_id=elsewhere.id, title="hidden", kind=ItemKind.EPIC), actor
    )
    await auth_roles.ensure_builtin_roles(db)
    baseline = await auth_roles.role_by_key(db, BuiltinRoleKey.BASELINE)
    baseline.permissions = []
    await db.flush()
    authz.forget_baseline(db)

    async def grant(user, target_project, atoms):
        role = await auth_roles.create_role(
            db, RoleCreate(key=f"bp{uuid.uuid4().hex[:6]}", name="R", permissions=atoms)
        )
        db.add(GlobalRoleGrant(project_id=target_project.id, user_id=user.id, role_id=role.id))
        await db.flush()

    outsider = await make_user(db, name="Outsider")
    await grant(outsider, project, ["item.read", "item.update"])
    own_only = await make_user(db, name="Own only")
    await grant(own_only, project, ["item.read", "item.update"])
    await grant(own_only, elsewhere, ["item.read@own"])

    for reader, reason in (
        (outsider, BulkSkipReason.FORBIDDEN),
        (own_only, BulkSkipReason.INVALID_TARGET),
    ):
        result = await bulk.bulk_update_items(
            db,
            ItemBulkUpdate(item_ids=[issues[1].id], patch=ItemBulkPatch(parent_id=hidden_epic.id)),
            reader,
        )
        assert result.updated == []
        [skipped] = result.skipped
        assert skipped.reason == reason
        if reason == BulkSkipReason.INVALID_TARGET:
            assert "not found" in (skipped.detail or "")
        assert (await items.get_item(db, issues[1].id, actor)).parent.id == epic.id
    # The same patch by someone who CAN read the target lands — the refusal above
    # was about the reader, not the epic.
    result = await bulk.bulk_update_items(
        db,
        ItemBulkUpdate(item_ids=[issues[1].id], patch=ItemBulkPatch(parent_id=hidden_epic.id)),
        actor,
    )
    assert result.updated == [issues[1].id] and result.skipped == []
