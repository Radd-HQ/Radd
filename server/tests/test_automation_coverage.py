"""Coverage (RADD-1267): the item actions that were missing, the project gate,
the switched-on triggers, and the pages plugin's own action nodes."""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.kernel import registries
from radd.modules.auth.models import User
from radd.modules.automations import catalog, engine, gates
from radd.modules.automations.conditions import EventFacts
from radd.modules.automations.planning import _plan
from radd.modules.automations.types import ActionType, PlanKind
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemVisibility
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine_ = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(email=f"cov-{uuid.uuid4().hex[:8]}@example.com", name="Coverage Admin", instance_role="admin")
    db.add(user)
    await db.flush()
    return user


async def _project(db, prefix="CV"):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"{prefix}{uuid.uuid4().hex[:4].upper()}", name="Coverage")
    )


def _facts(**payload) -> EventFacts:
    return EventFacts(event_type="item.updated", actor_id=None, actor_email=None, actor_name=None, payload=payload)


async def _planned(db, admin, item, project, action: str, params: dict):
    row = await items_service.require_item(db, item.id)
    return await _plan(
        db, {"type": action, "params": params}, row, project, admin,
        facts=engine._manual_facts(), rule_name="coverage",
    )


# --- the project gate ---------------------------------------------------------


def test_project_gate_reads_the_event_ref_or_the_item_ref():
    assert gates.project_is(_facts(project={"id": "x", "key": "TD", "name": "T"}), {"projects": ["td"]})
    assert gates.project_is(_facts(item={"project": {"key": "OPS"}}), {"projects": ["OPS", "TD"]})
    assert not gates.project_is(_facts(item={"project": {"key": "OPS"}}), {"projects": ["TD"]})
    assert gates.project_is(_facts(item={"project": {"key": "OPS"}}), {"projects": ["TD"], "negate": True})
    assert not gates.project_is(_facts(), {"projects": ["TD"]})
    assert not gates.project_is(_facts(project={"key": "TD"}), {"projects": []})


# --- the switched-on triggers -------------------------------------------------


def test_the_missing_triggers_are_now_triggers():
    triggers = catalog.TRIGGERS
    for event_type in (
        "user.created", "user.updated", "worklog.estimate_changed", "access.granted",
        "access.revoked", "page_space.public_access_changed", "sla_policy.created",
        "sla_policy.updated", "sla_policy.deleted",
    ):
        assert event_type in triggers, event_type
    assert triggers["worklog.estimate_changed"].item_scoped


def test_the_pages_plugin_contributes_its_two_actions():
    assert registries.automation_nodes["page.comment"].subject == "page"
    assert registries.automation_nodes["page.move"].subject == "page"


# --- the item actions: each resolves, and each skips with a reason ------------


async def test_field_actions_plan_item_updates(db, admin):
    project = await _project(db)
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    epic = await items_service.create_item(db, ItemCreate(project_id=project.id, title="e", kind="epic"), admin)

    plan = await _planned(db, admin, item, project, ActionType.SET_PARENT, {"parent": epic.key.lower()})
    assert plan.kind is PlanKind.ITEM_UPDATE and plan.item_update.parent_id == epic.id
    plan = await _planned(db, admin, item, project, ActionType.SET_PARENT, {"parent": "none"})
    assert plan.kind is PlanKind.ITEM_UPDATE and plan.item_update.parent_id is None
    plan = await _planned(db, admin, item, project, ActionType.SET_PARENT, {"parent": "NOPE-1"})
    assert plan.kind is PlanKind.SKIP and "no item" in plan.detail

    plan = await _planned(db, admin, item, project, ActionType.SET_TYPE, {"type": "Bug"})
    assert plan.kind is PlanKind.ITEM_UPDATE and plan.item_update.type_id is not None
    plan = await _planned(db, admin, item, project, ActionType.SET_TYPE, {"type": "Saga"})
    assert plan.kind is PlanKind.SKIP and "types:" in plan.detail

    plan = await _planned(db, admin, item, project, ActionType.SET_REPORTER, {"reporter": admin.email})
    assert plan.kind is PlanKind.ITEM_UPDATE and plan.item_update.reporter_id == admin.id
    plan = await _planned(db, admin, item, project, ActionType.SET_REPORTER, {"reporter": "ghost@example.invalid"})
    assert plan.kind is PlanKind.SKIP

    plan = await _planned(db, admin, item, project, ActionType.SET_DATES, {"start": "today", "target": "none"})
    assert plan.kind is PlanKind.ITEM_UPDATE
    assert plan.item_update.start_date == date.today()
    assert "target_date" in plan.item_update.model_fields_set and plan.item_update.target_date is None
    plan = await _planned(db, admin, item, project, ActionType.SET_DATES, {"start": "soonish", "target": ""})
    assert plan.kind is PlanKind.SKIP and "not a date" in plan.detail

    plan = await _planned(db, admin, item, project, ActionType.SET_ESTIMATE, {"points": "5"})
    assert plan.kind is PlanKind.ITEM_UPDATE and plan.item_update.estimate_points == 5
    plan = await _planned(db, admin, item, project, ActionType.SET_ESTIMATE, {"points": "many"})
    assert plan.kind is PlanKind.SKIP

    plan = await _planned(db, admin, item, project, ActionType.SET_FLAG, {"flagged": False})
    assert plan.kind is PlanKind.ITEM_UPDATE and plan.item_update.flagged is False
    plan = await _planned(db, admin, item, project, ActionType.SET_VISIBILITY, {"visibility": "internal"})
    assert plan.kind is PlanKind.ITEM_UPDATE and plan.item_update.visibility is ItemVisibility.INTERNAL


async def test_verb_actions_plan_and_apply(db, admin):
    project = await _project(db)
    other = await _project(db, "CW")
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    target = await items_service.create_item(db, ItemCreate(project_id=project.id, title="u"), admin)

    plan = await _planned(db, admin, item, project, ActionType.LINK_ITEM, {"target": target.key, "link_type": "relates"})
    assert plan.kind is PlanKind.LINK and plan.link == (target.id, "relates")
    await engine._apply_plan(db, plan, await items_service.require_item(db, item.id), admin, rule_name="cov")
    read = await items_service.get_item(db, item.id, actor=admin)
    assert any(edge.link_type == "relates" for edge in [*read.links.outgoing, *read.links.incoming])
    plan = await _planned(db, admin, item, project, ActionType.LINK_ITEM, {"target": item.key, "link_type": "relates"})
    assert plan.kind is PlanKind.SKIP and "itself" in plan.detail

    plan = await _planned(db, admin, item, project, ActionType.ARCHIVE_ITEM, {"archived": True})
    assert plan.kind is PlanKind.ARCHIVE and plan.archive is True
    await engine._apply_plan(db, plan, await items_service.require_item(db, item.id), admin, rule_name="cov")
    assert (await items_service.require_item(db, item.id)).archived_at is not None
    plan = await _planned(db, admin, item, project, ActionType.ARCHIVE_ITEM, {"archived": True})
    assert plan.kind is PlanKind.SKIP and "already" in plan.detail

    plan = await _planned(db, admin, item, project, ActionType.ADD_WATCHER, {"user": "reporter"})
    assert plan.kind is PlanKind.WATCH and plan.person == admin.id
    await engine._apply_plan(db, plan, await items_service.require_item(db, item.id), admin, rule_name="cov")
    from radd.modules.notify import service as notify

    assert admin.id in await notify.watcher_ids(db, item.id)
    plan = await _planned(db, admin, item, project, ActionType.ADD_WATCHER, {"user": "assignee"})
    assert plan.kind is PlanKind.SKIP and "no assignee" in plan.detail

    plan = await _planned(db, admin, item, project, ActionType.ADD_PARTICIPANT, {"user": admin.email})
    assert plan.kind is PlanKind.PARTICIPANT and plan.person == admin.id

    plan = await _planned(db, admin, item, project, ActionType.MOVE_TO_PROJECT, {"project": other.key})
    assert plan.kind is PlanKind.MOVE and plan.move_to == other.id
    plan = await _planned(db, admin, item, project, ActionType.MOVE_TO_PROJECT, {"project": project.key})
    assert plan.kind is PlanKind.SKIP and "already" in plan.detail
    plan = await _planned(db, admin, target, project, ActionType.MOVE_TO_PROJECT, {"project": other.key})
    await engine._apply_plan(db, plan, await items_service.require_item(db, target.id), admin, rule_name="cov")
    assert (await items_service.require_item(db, target.id)).project_id == other.id


# --- the page nodes -----------------------------------------------------------


async def test_page_comment_and_move_plan_against_the_page_subject(db, admin):
    from radd.modules.pages import service as pages, spaces
    from radd.modules.pages.automation import plan_comment, plan_move, apply_comment
    from radd.modules.pages.schemas import PageCreate, PageSpaceCreate
    from radd.modules.comments import service as comments

    slug = f"cov-{uuid.uuid4().hex[:6]}"
    space = await spaces.create_space(db, PageSpaceCreate(name="Cov", slug=slug), admin.id)
    root = await pages.create_page(db, PageCreate(space_id=space.id, title="Root", body="r"), admin.id)
    page = await pages.create_page(db, PageCreate(space_id=space.id, title="Leaf", body="l"), admin.id)

    class Ctx:
        def __init__(self, params, ids):
            self.session, self.actor, self.subject_ids = db, admin, ids
            self.node = type("N", (), {"params": params})()

    plan = await plan_comment(Ctx({"body": "stale?"}, (page.id,)))
    assert plan.resolves and plan.page_id == page.id
    await apply_comment(Ctx({}, ()), plan)
    listed = await comments.list_comments(db, page.id, admin, entity_type="page")
    assert any(c.body == "stale?" for c in listed)
    assert not (await plan_comment(Ctx({"body": ""}, (page.id,)))).resolves
    assert not (await plan_comment(Ctx({"body": "x"}, ()))).resolves

    plan = await plan_move(Ctx({"parent": str(root.number)}, (page.id,)))
    assert plan.resolves and plan.parent_id == root.id
    assert not (await plan_move(Ctx({"parent": "nope"}, (page.id,)))).resolves
    assert not (await plan_move(Ctx({"parent": str(page.number)}, (page.id,)))).resolves
    assert not (await plan_move(Ctx({"parent": ""}, (page.id,)))).resolves  # already at the root
