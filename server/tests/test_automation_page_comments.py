"""Page comments, discussion and replies reach automations (RADD-1248).

- the comment event carries the PAGE ref (title, path, space) and
  `parent_comment_id`;
- a comment whose parent is a page runs the itemless path instead of being
  dropped as "item vanished";
- `gate.comment` tells a reply from a root, `gate.page_space` a space from
  another, and the page/comment tokens render;
- end to end: "on a comment in space runbooks, create an item in OPS naming
  the page" fires on a page discussion comment AND on a reply, and not on an
  item comment.

DB-backed, flushed never committed.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth.models import User
from radd.modules.automations import engine, gates, service as automations, templating
from radd.modules.automations.conditions import EventFacts
from radd.modules.automations.schemas import RuleCreate
from radd.modules.comments import service as comments, threads
from radd.modules.comments.schemas import CommentCreate, CommentReplyCreate
from radd.modules.comments.types import CommentEvent
from radd.modules.events import service as events
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.pages import service as pages, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine_ = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(email=f"pc-{uuid.uuid4().hex[:8]}@example.com", name="Page Commenter", instance_role="admin")
    db.add(user)
    await db.flush()
    return user


async def _space_and_page(db, admin, slug: str):
    space = await spaces.create_space(db, PageSpaceCreate(name=f"Space {slug}", slug=slug), admin.id)
    parent = await pages.create_page(db, PageCreate(space_id=space.id, title="Onboarding", body="x"), admin.id)
    page = await pages.create_page(
        db, PageCreate(space_id=space.id, title="Laptops", body="y", parent_id=parent.id), admin.id
    )
    return space, page


async def _last_event(db, event_type: str, since: int):
    rows = await events.read_after(db, since, 200)
    matching = [e for e in rows if e.event_type == event_type]
    assert matching, f"no {event_type} after {since}"
    return matching[-1]


# --- the payload -----------------------------------------------------------------


async def test_a_page_comment_event_carries_the_page_ref_and_the_thread_parent(db, admin):
    slug = f"runbooks-{uuid.uuid4().hex[:6]}"
    space, page = await _space_and_page(db, admin, slug)
    head = await events.latest_event_id(db)
    root = await comments.create_comment(db, page.id, CommentCreate(body="a remark"), admin, entity_type="page")
    created = await _last_event(db, CommentEvent.CREATED.value, head)
    payload = created.payload
    assert payload["item"] is None
    assert payload["parent_comment_id"] is None
    assert payload["page"]["id"] == str(page.id)
    assert payload["page"]["title"] == "Laptops"
    assert payload["page"]["path"] == "onboarding/laptops"
    assert payload["page"]["space"]["slug"] == slug

    head = await events.latest_event_id(db)
    await threads.create_reply(db, root.id, CommentReplyCreate(body="a reply"), admin)
    reply_event = await _last_event(db, CommentEvent.CREATED.value, head)
    assert reply_event.payload["parent_comment_id"] == str(root.id)
    assert reply_event.payload["page"]["number"] == page.number


# --- the gates and the tokens (pure) ---------------------------------------------


def _facts(**payload) -> EventFacts:
    return EventFacts(event_type="comment.created", actor_id=None, actor_email=None, actor_name=None, payload=payload)


def test_gate_comment_tells_a_reply_from_a_root_and_public_from_internal():
    root = _facts(parent_comment_id=None, visibility="public", excerpt="hi")
    reply = _facts(parent_comment_id=str(uuid.uuid4()), visibility="internal", excerpt="hi")
    assert gates.comment_is(root, {"thread": "root"}) and not gates.comment_is(root, {"thread": "reply"})
    assert gates.comment_is(reply, {"thread": "reply"}) and not gates.comment_is(reply, {"thread": "root"})
    assert gates.comment_is(reply, {"thread": "any", "visibility": "internal"})
    assert not gates.comment_is(root, {"visibility": "internal"})
    # Not a comment event at all: the gate cannot be asked.
    assert not gates.comment_is(_facts(item={"id": "x"}), {"thread": "any"})


def test_gate_page_space_reads_either_ref_shape():
    page_event = _facts(page={"id": "p"}, page_space={"slug": "Runbooks"})
    page_comment = _facts(page={"id": "p", "space": {"slug": "runbooks"}})
    item_comment = _facts(item={"id": "i"}, page=None)
    assert gates.page_space_is(page_event, {"spaces": ["runbooks"]})
    assert gates.page_space_is(page_comment, {"spaces": ["RUNBOOKS", "other"]})
    assert not gates.page_space_is(page_comment, {"spaces": ["other"]})
    assert gates.page_space_is(page_comment, {"spaces": ["other"], "negate": True})
    assert not gates.page_space_is(item_comment, {"spaces": ["runbooks"]})
    assert not gates.page_space_is(page_comment, {"spaces": []})


def test_page_and_comment_tokens_render_from_the_refs():
    facts = _facts(
        page={"id": "p", "number": 42, "title": "Laptops", "path": "onboarding/laptops", "space": {"slug": "runbooks"}},
        excerpt="TODO: order chargers", visibility="public", parent_comment_id=None,
    )
    render = templating.Renderer(facts)
    assert render("{{page.title}} ({{page.space}}/{{page.path}})") == "Laptops (runbooks/onboarding/laptops)"
    assert render("{{page.url}}").endswith("/pages?pageId=42")
    assert render("{{comment.excerpt}} [{{comment.visibility}}] parent={{comment.parent_id}}") == (
        "TODO: order chargers [public] parent="
    )
    # An item event has no page: the tokens stay verbatim, like any unresolved token.
    assert templating.Renderer(_facts(item={"id": "i"}))("{{page.title}}") == "{{page.title}}"


# --- end to end ---------------------------------------------------------------------


def _graph(trigger: str, gate: dict, action: dict) -> dict:
    return {
        "name": "page comments → work",
        "nodes": [
            {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": trigger}},
            {"id": "g", "kind": "gate", "type": gate["type"], "params": gate["params"]},
            {"id": "a", "kind": "action", "type": f"action.{action['type']}", "params": action["params"]},
        ],
        "edges": [
            {"source": "t", "port": "out", "target": "g"},
            {"source": "g", "port": "true", "target": "a"},
        ],
    }


async def _created_titles(db, project_id) -> list[str]:
    rows = await db.execute(select(WorkItem.title).where(WorkItem.project_id == project_id).order_by(WorkItem.number))
    return list(rows.scalars())


async def test_a_page_comment_in_the_space_creates_work_and_an_item_comment_does_not(db, admin):
    slug = f"runbooks-{uuid.uuid4().hex[:6]}"
    space, page = await _space_and_page(db, admin, slug)
    ops = await projects_service.create_project(db, ProjectCreate(key=f"OP{uuid.uuid4().hex[:4].upper()}", name="Ops"))
    await automations.create_rule(
        db,
        RuleCreate.model_validate(_graph(
            CommentEvent.CREATED.value,
            {"type": "gate.page_space", "params": {"spaces": [slug]}},
            {"type": "create_item", "params": {"project": ops.key, "title": "{{page.title}}: {{comment.excerpt}}"}},
        )),
        admin.id,
    )

    head = await events.latest_event_id(db)
    root = await comments.create_comment(db, page.id, CommentCreate(body="TODO order chargers"), admin, entity_type="page")
    await engine.apply_event(db, await _last_event(db, CommentEvent.CREATED.value, head))
    assert await _created_titles(db, ops.id) == ["Laptops: TODO order chargers"]

    # A reply is a comment too — same trigger, same gate, same result.
    head = await events.latest_event_id(db)
    await threads.create_reply(db, root.id, CommentReplyCreate(body="and docks"), admin)
    await engine.apply_event(db, await _last_event(db, CommentEvent.CREATED.value, head))
    assert await _created_titles(db, ops.id) == ["Laptops: TODO order chargers", "Laptops: and docks"]

    # An ITEM comment: the gate asks about a page and there is none.
    other = await projects_service.create_project(db, ProjectCreate(key=f"OT{uuid.uuid4().hex[:4].upper()}", name="Other"))
    item = await items.create_item(db, ItemCreate(project_id=other.id, title="an issue"), admin)
    head = await events.latest_event_id(db)
    await comments.create_comment(db, item.id, CommentCreate(body="TODO on an item"), admin)
    await engine.apply_event(db, await _last_event(db, CommentEvent.CREATED.value, head))
    assert await _created_titles(db, ops.id) == ["Laptops: TODO order chargers", "Laptops: and docks"]


async def test_gate_comment_reply_fires_on_replies_only_on_both_surfaces(db, admin):
    ops = await projects_service.create_project(db, ProjectCreate(key=f"RP{uuid.uuid4().hex[:4].upper()}", name="Replies"))
    await automations.create_rule(
        db,
        RuleCreate.model_validate(_graph(
            CommentEvent.CREATED.value,
            {"type": "gate.comment", "params": {"thread": "reply"}},
            {"type": "create_item", "params": {"project": ops.key, "title": "reply: {{comment.excerpt}}"}},
        )),
        admin.id,
    )
    item = await items.create_item(db, ItemCreate(project_id=ops.id, title="seed"), admin)
    head = await events.latest_event_id(db)
    root = await comments.create_comment(db, item.id, CommentCreate(body="root on an item"), admin)
    await engine.apply_event(db, await _last_event(db, CommentEvent.CREATED.value, head))
    assert await _created_titles(db, ops.id) == ["seed"]

    head = await events.latest_event_id(db)
    await threads.create_reply(db, root.id, CommentReplyCreate(body="item reply"), admin)
    await engine.apply_event(db, await _last_event(db, CommentEvent.CREATED.value, head))
    assert await _created_titles(db, ops.id) == ["seed", "reply: item reply"]

    _space, page = await _space_and_page(db, admin, f"sp-{uuid.uuid4().hex[:6]}")
    head = await events.latest_event_id(db)
    page_root = await comments.create_comment(db, page.id, CommentCreate(body="root on a page"), admin, entity_type="page")
    await engine.apply_event(db, await _last_event(db, CommentEvent.CREATED.value, head))
    head = await events.latest_event_id(db)
    await threads.create_reply(db, page_root.id, CommentReplyCreate(body="page reply"), admin)
    await engine.apply_event(db, await _last_event(db, CommentEvent.CREATED.value, head))
    assert await _created_titles(db, ops.id) == ["seed", "reply: item reply", "reply: page reply"]
