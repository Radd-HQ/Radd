"""RADD-1393 — My Work's widgets from optional plugins are CONTRIBUTED.

Dashboards became core, and a core module may not name an optional plugin
(RADD-1349). My Work used to hardcode "Awaiting my approval" and ask
`approvals.service` whether to suggest it; now approvals contributes a
`WidgetTypeSpec(personal=True, suggest=...)` and dashboards reads the registry.
This pins both halves against the real plugin, withdrawn the way a runtime
disable leaves it (`registries.unregister_plugin`):

* withdrawn — the type is not a My Work type (a new one is refused), it is not
  suggested even to someone with a pending approval, and a widget already on the
  person's layout still saves (My Work stays editable while the plugin is off);
* registered — a person with something to decide gets it suggested, titled by the
  spec's label; someone with nothing pending does not; a shared dashboard refuses it.

DB-backed, flushed never committed; the session rolls back at teardown.
"""

import uuid
from contextlib import contextmanager

import pytest
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.kernel.registry import registries
from radd.modules.approvals import service as approvals
from radd.modules.approvals.schemas import ApprovalRequestCreate
from radd.modules.approvals.types import ApprovalCheck, ApprovalWidget
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.dashboards import personal
from radd.modules.dashboards.router import _parse_widget_body
from radd.modules.dashboards.schemas import WidgetLayoutSave
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.workflow import service as workflow, transitions
from radd.modules.workflow.schemas import TransitionCreate, TransitionRule
from radd.modules.workflow.types import TransitionMode

AWAITING = ApprovalWidget.AWAITING.value


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, role: InstanceRole = InstanceRole.MEMBER) -> User:
    user = User(email=f"mw-{uuid.uuid4().hex[:8]}@example.com", name="My Work", instance_role=role.value)
    db.add(user)
    await db.flush()
    return user


async def _approver_with_pending(db) -> User:
    """A person named on a require_approval rule, with one request awaiting them."""
    requester = await _user(db, InstanceRole.ADMIN)
    approver = await _user(db)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MW{uuid.uuid4().hex[:4].upper()}", name="My Work")
    )
    await settings_service.set_value(
        db, SettingKey.WORKFLOW_TRANSITION_MODE, SettingScope.PROJECT, project.id,
        TransitionMode.GUARDS.value,
    )
    done = next(s for s in await workflow.list_states(db, project.id) if s.name == "Done")
    rule = TransitionRule(
        check=ApprovalCheck.REQUIRE_APPROVAL,
        params={"approvers": [{"kind": "user", "id": str(approver.id)}]},
    )
    await transitions.create_transition(
        db, TransitionCreate(project_id=project.id, to_state_id=done.id, rules=[rule])
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="decide"), requester)
    await approvals.create_request(db, item.id, ApprovalRequestCreate(to_state_id=done.id), requester)
    assert await approvals.has_pending(db, approver), "the fixture must leave a pending approval"
    return approver


def _widget(widget_id: str) -> dict:
    return {"id": widget_id, "widget_type": AWAITING, "title": None, "width": 4,
            "height": 280, "collapsed": False, "position": 0, "config": {}}


@contextmanager
def withdrawn(name: str):
    """The plugin gone from the kernel registries, as a runtime disable leaves it."""
    plugin = registries.plugins[name]
    registries.unregister_plugin(plugin)
    try:
        yield
    finally:
        registries.register_plugin(plugin)


async def test_withdrawn_approvals_is_neither_offered_nor_suggested(db):
    approver = await _approver_with_pending(db)
    with withdrawn("approvals"):
        assert not personal.is_personal(AWAITING)
        suggested = [w["widget_type"] for w in await personal.suggested_defaults(db, approver)]
        assert AWAITING not in suggested
        # A NEW approvals widget is refused on My Work while the plugin is off…
        with pytest.raises(RequestValidationError):
            await personal.save(db, approver, WidgetLayoutSave(widgets=[_widget(str(uuid.uuid4()))], expected=[]))


async def test_a_widget_already_on_my_work_survives_its_plugin_being_off(db):
    """…but one the person already has keeps its place, so collapsing or moving
    anything else on My Work does not fail over a plugin they cannot switch on."""
    approver = await _approver_with_pending(db)
    widget_id = str(uuid.uuid4())
    saved = await personal.save(db, approver, WidgetLayoutSave(widgets=[_widget(widget_id)], expected=[]))
    with withdrawn("approvals"):
        again = await personal.save(
            db, approver,
            WidgetLayoutSave(widgets=[{**_widget(widget_id), "collapsed": True}], expected=saved),
        )
    assert [(w["id"], w["widget_type"], w["collapsed"]) for w in again] == [(widget_id, AWAITING, True)]


async def test_registered_approvals_is_suggested_to_whoever_has_something_to_decide(db):
    approver = await _approver_with_pending(db)
    bystander = await _user(db)
    assert personal.is_personal(AWAITING)
    mine = {w["widget_type"]: w for w in await personal.suggested_defaults(db, approver)}
    assert mine[AWAITING]["title"] == "Awaiting my approval"
    assert AWAITING not in {w["widget_type"] for w in await personal.suggested_defaults(db, bystander)}
    # It shows the viewer's own queue, so it belongs on My Work — never a shared dashboard.
    with pytest.raises(RequestValidationError, match="My Work widget"):
        _parse_widget_body(_widget(str(uuid.uuid4())))
