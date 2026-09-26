"""The audit ledger (spec 123, RADD-1169).

What `emit` derives (project, label, search text), what the filters do
(project, changed field, source, noise), and who may read what: an instance
admin the whole instance, a project manager one project — with item rows
redacted through the same seam the History tab uses.

DB-backed tests are flushed, never committed; the session rolls back at teardown.
"""

import uuid

import pytest
from sqlalchemy import text

from radd.exceptions import ForbiddenError
from radd.kernel import registries
from radd.modules.audit import service as audit
from radd.modules.auth import grants
from radd.modules.auth.models import User
from radd.modules.auth.roles import role_by_key
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.events import service as events
from radd.modules.events.models import Event
from radd.modules.events.types import EventSource
from radd.modules.items import service as items
from radd.modules.items.enums import ItemEvent
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

from _factories import make_project, make_user


@pytest.fixture
async def admin(db) -> User:
    return await make_user(db, role=InstanceRole.ADMIN, name="Ledger Admin")


@pytest.fixture
async def project(db, admin):
    return await make_project(db, "LG", "Ledger", actor=admin)


@pytest.fixture
async def item(db, admin, project):
    created = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Ledger issue"), admin
    )
    await items.update_item(db, created.id, ItemUpdate(title="Renamed issue"), admin)
    await db.flush()
    return created


# --- what emit derives -----------------------------------------------------------


async def test_emit_derives_project_label_and_search_text(db, admin, project, item):
    row = (await events.query_events(db, event_types=[ItemEvent.UPDATED], entity_id=str(item.id)))[0]
    assert row.project_id == project.id
    assert row.entity_label == f"{item.key} Renamed issue"
    assert "Renamed issue" in row.search_text and "Ledger issue" in row.search_text
    assert "title" in row.search_text


async def test_emit_adds_the_entitys_own_ref_when_missing(db, admin, project):
    await events.emit(
        db,
        event_type="project.updated",
        entity_type="project",
        entity_id=project.id,
        actor_id=admin.id,
        payload={"key": project.key},
        changes=[{"field": "name", "from": "a", "to": "b"}],
    )
    row = (await events.query_events(db, event_types=["project.updated"], entity_id=str(project.id)))[0]
    assert row.payload["project"]["key"] == project.key
    assert row.project_id == project.id
    assert row.entity_label == f"{project.key} Ledger"


# --- the filters ------------------------------------------------------------------


async def test_changed_field_project_and_text_filters(db, admin, project, item):
    hits = await audit.audit_log(db, actor=admin, project_id=project.id, changed_field="title")
    assert [h.id for h in hits] and all(
        any(c["field"] == "title" for c in h.changes) for h in hits
    )
    assert await audit.audit_log(db, actor=admin, project_id=project.id, changed_field="assignee") == []
    found = await audit.audit_log(db, actor=admin, q="Renamed issue")
    assert any(h.entity_label == f"{item.key} Renamed issue" for h in found)
    people = await audit.audit_log(db, actor=admin, project_id=project.id, source=EventSource.PEOPLE)
    assert people and all(h.actor is not None and not h.automated for h in people)
    assert await audit.audit_log(db, actor=admin, project_id=project.id, source=EventSource.AUTOMATIONS) == []


async def test_noise_is_hidden_unless_asked_for(db, admin):
    assert registries.event_types["notification.created"].audited is False
    marker = f"noise-{uuid.uuid4().hex[:8]}"
    await events.emit(
        db,
        event_type="notification.created",
        entity_type="notification",
        entity_id=uuid.uuid4(),
        payload={"name": marker},
    )
    assert await audit.audit_log(db, actor=admin, q=marker) == []
    shown = await audit.audit_log(db, actor=admin, q=marker, include_noise=True)
    assert [h.entity_label for h in shown] == [marker]


async def test_entries_carry_labels_refs_and_project(db, admin, project, item):
    entry = (await audit.audit_log(db, actor=admin, project_id=project.id, changed_field="title"))[0]
    assert entry.event_label == "Item updated" and entry.event_group == "Items"
    assert entry.refs["item"]["key"] == item.key
    assert entry.project is not None and entry.project.key == project.key


def test_catalog_labels_every_registered_type():
    cat = audit.catalog()
    by_key = {e.event_type: e for e in cat.event_types}
    assert by_key["setting.changed"].label == "Setting changed"
    assert by_key["setting.changed"].has_changes is True
    assert by_key["mail.failed"].audited is False
    entity = {e.key: e.label for e in cat.entity_types}
    assert entity["item"] == "Issue" and entity["storage_host"] == "Storage host"


# --- who may read what -----------------------------------------------------------


async def test_project_manager_reads_only_their_project(db, admin, project, item):
    manager = await make_user(db, name="Manager")
    other = await projects_service.create_project(
        db, ProjectCreate(key=f"OT{uuid.uuid4().hex[:4].upper()}", name="Other"), actor_id=admin.id
    )
    role = await role_by_key(db, BuiltinRoleKey.MANAGER.value)
    await grants.create_grant(db, role.id, user_id=manager.id, project_id=project.id, actor_id=admin.id)

    with pytest.raises(ForbiddenError):
        await audit.audit_log(db, actor=manager)
    with pytest.raises(ForbiddenError):
        await audit.audit_log(db, actor=manager, project_id=other.id)
    mine = await audit.audit_log(db, actor=manager, project_id=project.id)
    assert mine and all(h.project is not None and h.project.id == project.id for h in mine)


async def test_backfill_shape_matches_emit(db):
    """The migration's SQL and `emit` must agree on what a label is — a row
    written before spec 123 reads the same as one written after."""
    row = Event(
        event_type="item.updated",
        entity_type="item",
        entity_id=str(uuid.uuid4()),
        payload={"item": {"key": "BF-1", "title": "Backfilled", "project": {"id": str(uuid.uuid4())}}},
    )
    db.add(row)
    await db.flush()
    await db.execute(
        text(
            "UPDATE events SET entity_label = CONCAT_WS(' ', payload -> entity_type ->> 'key', "
            "payload -> entity_type ->> 'title') WHERE id = :id"
        ),
        {"id": row.id},
    )
    await db.refresh(row)
    assert row.entity_label == "BF-1 Backfilled"


async def test_audit_destination_is_owned_and_does_not_rewrite_stored_events(db, admin, project, item):
    from radd.modules.items import plugin
    before = (await audit.audit_log(db, actor=admin, project_id=project.id, changed_field='title'))[0]
    assert before.entity_url == f'/issues/{item.key}'
    assert before.entity_owner == 'items'
    spec = registries.entity_links.pop('item')
    owner = registries.entity_link_owners.pop('item')
    try:
        after = (await audit.audit_log(db, actor=admin, project_id=project.id, changed_field='title'))[0]
        assert after.entity_url is None and after.entity_owner is None
        assert after.entity_label == before.entity_label
        assert after.changes == before.changes
    finally:
        registries.entity_links['item'] = spec
        registries.entity_link_owners['item'] = owner
    restored = (await audit.audit_log(db, actor=admin, project_id=project.id, changed_field='title'))[0]
    assert restored.entity_owner == plugin.name
    assert restored.entity_url == before.entity_url


async def test_access_endpoint_uses_the_exact_ledger_scope(db, admin, project):
    from radd.modules.audit.router import audit_access
    from radd.modules.auth.scopes import parse_scope

    manager = await make_user(db, name="Scoped manager")
    outsider = await make_user(db, name="Outsider")
    other = await projects_service.create_project(
        db, ProjectCreate(key=f"AC{uuid.uuid4().hex[:4].upper()}", name="Other scope"), actor_id=admin.id
    )
    role = await role_by_key(db, BuiltinRoleKey.MANAGER.value)
    await grants.create_grant(db, role.id, user_id=manager.id, project_id=project.id, actor_id=admin.id)
    for actor, scope, expected, instance_wide in (
        (admin, None, True, True), (admin, project.id, True, True),
        (manager, None, False, False), (manager, project.id, True, False),
        (manager, other.id, False, False), (outsider, project.id, False, False),
    ):
        result = await audit_access(db, actor, scope)
        assert result.allowed == expected and result.instance_wide == instance_wide
        if expected:
            await audit.require_audit_scope(db, actor, scope)
        else:
            with pytest.raises(ForbiddenError):
                await audit.require_audit_scope(db, actor, scope)
    # An admin account with a constrained credential is not an instance-wide reader.
    admin.token_scope = parse_scope({"global": ["item.read"]})
    try:
        result = await audit_access(db, admin, None)
        assert not result.allowed and not result.instance_wide
    finally:
        admin.token_scope = None


async def test_audit_and_items_own_their_navigation_contract(admin):
    """Audit and Items are core plugins, so their UI is bundled with the host (RADD-1373): the
    capabilities list them as loaded plugins with no remote, and Audit still declares its nav."""
    from radd.modules.capabilities.router import get_capabilities
    manifest = await get_capabilities(admin)
    remotes = {remote.name for remote in manifest.remotes}
    for owner in ("audit", "items"):
        assert owner in manifest.plugins
        assert owner not in remotes
    nav = next(row for row in manifest.nav if row.plugin == "audit")
    assert nav.path == "/settings/audit"
    assert nav.requires_any_project == ["project.manage"]
