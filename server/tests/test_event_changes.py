"""The kernel change primitive (spec 123, RADD-1166).

Three invariants every module's audit trail depends on:

1. `kernel.changes.diff` produces the one shape the SPA renders and the
   consumers read — `{field, from, to}` scalars, `{field, added, removed}`
   collections, `{field}` alone for a hidden value — JSON-safe, in field order.
2. `events.emit` REFUSES an event whose spec declares `has_changes` when no diff
   is passed, and accepts `[]` as "nothing visible changed". A forgotten diff is
   a test failure, not a blank "updated" row an auditor finds a year later.
3. Every registered `*.updated` event type declares `has_changes=True`, and
   every event type a module's `*Event` enum can emit is REGISTERED (an
   unregistered type has no label in the audit catalog, no automation trigger,
   and escapes invariant 2). The allowlists below are the burn-down
   RADD-1167/RADD-1168 empty; an entry that no longer needs to be there fails
   the test so the lists cannot rot.
"""

import enum
import importlib
import inspect
import pkgutil
import uuid
from datetime import date, datetime
from enum import StrEnum

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.kernel import changes, registries
from radd.modules.events import service as events


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


# --- 1. the shape ---------------------------------------------------------------


class _Colour(StrEnum):
    RED = "red"


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_snapshot_is_json_safe():
    uid = uuid.uuid4()
    row = _Row(
        id=uid,
        when=datetime(2026, 9, 14, 6, 0),
        day=date(2026, 9, 14),
        colour=_Colour.RED,
        tags={"b", "a"},
        nested={"k": uid},
    )
    snap = changes.snapshot(row, ("id", "when", "day", "colour", "tags", "nested", "missing"))
    assert snap == {
        "id": str(uid),
        "when": "2026-09-14T06:00:00",
        "day": "2026-09-14",
        "colour": "red",
        "tags": ["a", "b"],
        "nested": {"k": str(uid)},
        "missing": None,
    }


def test_diff_scalars_collections_hidden_and_labels():
    before = {"name": "Old", "secret": "a", "perms": ["x", "y"], "same": 1, "note": None}
    after = {"name": "New", "secret": "b", "perms": ["y", "z"], "same": 1, "note": "hi"}
    out = changes.diff(before, after, hidden=("secret",), labels={"note": "Note"})
    assert out == [
        {"field": "name", "from": "Old", "to": "New"},
        {"field": "secret"},
        {"field": "perms", "added": ["z"], "removed": ["x"]},
        {"field": "note", "from": None, "to": "hi", "name": "Note"},
    ]


def test_diff_collection_of_dicts_compares_by_content():
    before = {"approvers": [{"id": "1", "name": "A"}]}
    after = {"approvers": [{"name": "A", "id": "1"}, {"id": "2", "name": "B"}]}
    assert changes.diff(before, after) == [
        {"field": "approvers", "added": [{"id": "2", "name": "B"}], "removed": []}
    ]


def test_diff_object_and_changed_fields():
    row = _Row(name="a", active=True)
    before = changes.snapshot(row, ("name", "active"))
    row.name = "b"
    row.active = False
    out = changes.diff_object(row, before)
    assert out == [
        {"field": "name", "from": "a", "to": "b"},
        {"field": "active", "from": True, "to": False},
    ]
    assert changes.changed_fields(out + [{"field": "name"}]) == ["name", "active"]


# --- 2. the refusal -------------------------------------------------------------


async def test_emit_refuses_a_promised_diff_that_is_missing(db):
    assert registries.event_types["item.updated"].has_changes
    with pytest.raises(events.ChangesRequired):
        await events.emit(
            db,
            event_type="item.updated",
            entity_type="item",
            entity_id=uuid.uuid4(),
            payload={"item": {"id": "x"}},
        )


async def test_emit_accepts_an_empty_diff_and_writes_it(db):
    await events.emit(
        db,
        event_type="item.updated",
        entity_type="item",
        entity_id=uuid.uuid4(),
        payload={"item": {"id": "x"}},
        changes=[],
    )
    await db.flush()
    row = (await events.query_events(db, event_types=["item.updated"], limit=1))[0]
    assert row.payload["changes"] == []


async def test_emit_without_a_spec_promise_needs_no_diff(db):
    await events.emit(
        db,
        event_type="item.created",
        entity_type="item",
        entity_id=uuid.uuid4(),
        payload={"item": {"id": "x"}},
    )


# --- 3. the contract ------------------------------------------------------------

#: `*.updated` (and `*.changed`) event types that do not yet declare
#: `has_changes`. The burn-down RADD-1167/RADD-1168 empty. Every entry here is a
#: settings edit an auditor sees as "updated" with nothing behind it.
UPDATED_WITHOUT_CHANGES_ALLOWLIST: set[str] = {
    "backup_schedule.updated",
    "comment.updated",
    "cycle.updated",
    "cycle_series.updated",
    "field.updated",
    "form.updated",
    "issue_type.updated",
    "page.updated",
    "page_space.updated",
    "release.updated",
    "state.updated",
    "team.updated",
    "vcs.updated",
    "weblink.updated",
    "workflow_transition.updated",
    "worklog.updated",
}


def _diff_bearing_types() -> set[str]:
    return {
        str(key)
        for key in registries.event_types
        if key.endswith(".updated") or key.endswith(".changed")
    }


def test_every_updated_event_declares_a_diff():
    undeclared = {
        key for key in _diff_bearing_types() if not registries.event_types[key].has_changes
    }
    missing = undeclared - UPDATED_WITHOUT_CHANGES_ALLOWLIST
    assert not missing, (
        "updated events that promise no diff (declare has_changes=True and emit "
        "changes=, or add to the burn-down allowlist):\n  " + "\n  ".join(sorted(missing))
    )
    stale = UPDATED_WITHOUT_CHANGES_ALLOWLIST - undeclared
    assert not stale, f"allowlist entries no longer needed: {sorted(stale)}"


#: Event types a module's `*Event` enum declares that no plugin registers as an
#: `EventTypeSpec` (48 on 2026-09-14). The audit found the class while seeding
#: the first allowlist: `role.updated`, `user.updated`, `view.updated`… are
#: emitted, land in the log, and have no label, no trigger, and no diff
#: promise anywhere. RADD-1168 registers them; the list is the burn-down.
UNREGISTERED_EVENT_TYPES_ALLOWLIST: set[str] = {
    "access.granted",
    "access.revoked",
    "auth.view_as_ended",
    "auth.view_as_started",
    "automation.created",
    "automation.deleted",
    "automation.scheduled",
    "automation.updated",
    "canned_response.created",
    "canned_response.deleted",
    "canned_response.updated",
    "dashboard.created",
    "dashboard.deleted",
    "dashboard.updated",
    "field.deleted",
    "form.deleted",
    "issue_type.deleted",
    "label.deleted",
    "label.updated",
    "ldap.login",
    "link_type.created",
    "link_type.deleted",
    "link_type.updated",
    "notification.created",
    "role.created",
    "role.deleted",
    "role.updated",
    "screen.updated",
    "sla_policy.created",
    "sla_policy.deleted",
    "sla_policy.updated",
    "sso.identity_linked",
    "sso.login",
    "state.deleted",
    "team.deleted",
    "user.created",
    "user.deleted",
    "user.updated",
    "view.card_preset.created",
    "view.card_preset.deleted",
    "view.card_preset.updated",
    "view.created",
    "view.deleted",
    "view.updated",
    "webhook_endpoint.created",
    "webhook_endpoint.deleted",
    "webhook_endpoint.updated",
    "worklog.estimate_changed",
}


def _enum_declared_event_types() -> set[str]:
    """Every member of every `*Event(StrEnum)` a module defines — what the
    tree CAN emit, as opposed to what it registered."""
    import radd.modules as modules_pkg

    declared: set[str] = set()
    for info in pkgutil.walk_packages(modules_pkg.__path__, "radd.modules."):
        try:
            module = importlib.import_module(info.name)
        except Exception:  # an optional dependency's module — not this test's concern
            continue
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, enum.StrEnum)
                and name.endswith("Event")
                and obj.__module__ == module.__name__
            ):
                declared.update(str(member.value) for member in obj)
    return declared


def test_every_emittable_event_type_is_registered():
    registered = {str(key) for key in registries.event_types}
    unregistered = _enum_declared_event_types() - registered
    missing = unregistered - UNREGISTERED_EVENT_TYPES_ALLOWLIST
    assert not missing, (
        "event types a module can emit but never registered (add an EventTypeSpec "
        "to the plugin, or to the burn-down allowlist):\n  " + "\n  ".join(sorted(missing))
    )
    stale = UNREGISTERED_EVENT_TYPES_ALLOWLIST - unregistered
    assert not stale, f"allowlist entries no longer needed: {sorted(stale)}"
