"""Notify planning core (spec 26) + the delivery choke point (RADD-971).

Pure, DB-free tests of the invariants everything else leans on: the actor is
never self-notified, one notification per user per event with personal types
(assigned/mentioned) beating ambient ones (state_changed/commented), auto-watch
sets, and the mention grammar. The full consumer (permission filtering, mention
resolution, email digests) is exercised against a live DB by the demo flows.

The last section is DB-backed, because the mute preference is now enforced at
the WRITE (`service.create_notification`) rather than in the outbox consumer —
and the whole point of that move is that the producers which never go near the
consumer inherit it. Testing the planner cannot see that; testing the seam alone
would prove nothing about the two callers that were broken. So those two callers
are driven for real. Rows are flushed, never committed; the session rolls back.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.notify import planner, service as notify_service
from radd.modules.notify.models import Notification
from radd.modules.notify.types import NotificationType

ACTOR = uuid.uuid4()
ASSIGNEE = uuid.uuid4()
WATCHER = uuid.uuid4()
MENTIONED = uuid.uuid4()
REPORTER = uuid.uuid4()


def _types_by_user(plan: planner.Plan) -> dict[uuid.UUID, NotificationType]:
    return {p.user_id: p.type for p in plan.notifications}


# --- mention grammar ---


def test_parse_mentions_token_and_email_forms():
    user_id = uuid.uuid4()
    ids, emails = planner.parse_mention_candidates(
        f"Ping @[Jane Doe]({user_id}) and @jane@example.com about this."
    )
    assert ids == {str(user_id)}
    assert emails == {"jane@example.com"}


def test_parse_mentions_empty_and_plain_text():
    assert planner.parse_mention_candidates("") == (set(), set())
    # A bare email without the @ prefix is not a mention.
    assert planner.parse_mention_candidates("mail jane@example.com please") == (set(), set())


# --- item created ---


def test_create_assigns_and_watches():
    payload = {"item": {"assignee": {"id": str(ASSIGNEE), "name": "A"}}}
    plan = planner.plan_item_created(payload, ACTOR, frozenset())
    assert plan.watch == {ACTOR, ASSIGNEE}
    assert _types_by_user(plan) == {ASSIGNEE: NotificationType.ASSIGNED}


def test_create_never_notifies_the_actor():
    # Self-assignment on create: watch yes, notification no.
    payload = {"item": {"assignee": {"id": str(ACTOR), "name": "A"}}}
    plan = planner.plan_item_created(payload, ACTOR, frozenset({ACTOR}))
    assert plan.watch == {ACTOR}
    assert plan.notifications == []


def test_create_mentions_notify():
    plan = planner.plan_item_created({"item": {"assignee": None}}, ACTOR, frozenset({MENTIONED}))
    assert _types_by_user(plan) == {MENTIONED: NotificationType.MENTIONED}


# --- item updated ---


def test_update_state_change_notifies_watchers_not_actor():
    payload = {
        "assignee": None,
        "changes": [{"field": "state", "from": "Todo", "to": "Done"}],
    }
    plan = planner.plan_item_updated(payload, ACTOR, frozenset({WATCHER, ACTOR}), frozenset())
    assert _types_by_user(plan) == {WATCHER: NotificationType.STATE_CHANGED}
    assert plan.notifications[0].detail == {"from": "Todo", "to": "Done"}


def test_update_assignment_beats_state_change():
    # New assignee also watches: one ASSIGNED notification, not two.
    payload = {
        "item": {"assignee": {"id": str(ASSIGNEE), "name": "A"}},
        "changes": [
            {"field": "assignee", "from": None, "to": "A"},
            {"field": "state", "from": "Todo", "to": "Doing"},
        ],
    }
    plan = planner.plan_item_updated(payload, ACTOR, frozenset({ASSIGNEE, WATCHER}), frozenset())
    assert _types_by_user(plan) == {
        ASSIGNEE: NotificationType.ASSIGNED,
        WATCHER: NotificationType.STATE_CHANGED,
    }


def test_update_without_relevant_changes_plans_nothing():
    payload = {"item": {"assignee": None}, "changes": [{"field": "title", "from": "a", "to": "b"}]}
    plan = planner.plan_item_updated(payload, ACTOR, frozenset({WATCHER}), frozenset())
    assert plan.notifications == [] and plan.watch == set()


# --- reporter auto-watch (spec 62) ---


def test_create_reporter_auto_watches_without_a_ping():
    payload = {"item": {"assignee": None, "reporter": {"id": str(REPORTER), "name": "R"}}}
    plan = planner.plan_item_created(payload, ACTOR, frozenset())
    assert plan.watch == {ACTOR, REPORTER}
    assert plan.notifications == []  # watching, not a notification


def test_create_without_reporter_watches_only_the_actor():
    plan = planner.plan_item_created({"item": {"assignee": None, "reporter": None}}, ACTOR, frozenset())
    assert plan.watch == {ACTOR}


def test_update_reporter_change_watches_the_new_reporter():
    payload = {
        "item": {"assignee": None, "reporter": {"id": str(REPORTER), "name": "R"}},
        "changes": [{"field": "reporter", "from": None, "to": "R"}],
    }
    plan = planner.plan_item_updated(payload, ACTOR, frozenset(), frozenset())
    assert plan.watch == {REPORTER}
    assert plan.notifications == []


def test_update_untouched_reporter_is_not_rewatched():
    # The snapshot always carries the reporter; only a `reporter` CHANGE watches
    # them (an unwatch must stick when unrelated fields move).
    payload = {
        "item": {"assignee": None, "reporter": {"id": str(REPORTER), "name": "R"}},
        "changes": [{"field": "title", "from": "a", "to": "b"}],
    }
    plan = planner.plan_item_updated(payload, ACTOR, frozenset(), frozenset())
    assert plan.watch == set()


# --- comment created ---


def test_comment_notifies_watchers_and_mentions_win():
    payload = {"excerpt": "hey", "visibility": "public"}
    plan = planner.plan_comment_created(
        payload, ACTOR, frozenset({WATCHER, MENTIONED, ACTOR}), frozenset({MENTIONED})
    )
    assert plan.watch == {ACTOR}  # author auto-watches
    assert _types_by_user(plan) == {
        MENTIONED: NotificationType.MENTIONED,
        WATCHER: NotificationType.COMMENTED,
    }


def test_comment_carries_visibility_for_internal_filtering():
    # The consumer drops internal-comment recipients without comment.read_internal;
    # the planner must thread visibility through for that check.
    payload = {"excerpt": "secret", "visibility": "internal"}
    plan = planner.plan_comment_created(payload, ACTOR, frozenset({WATCHER}), frozenset())
    assert plan.notifications[0].detail["visibility"] == "internal"


# --- the mute is enforced at the write, so every producer inherits it (RADD-971) ---


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name: str) -> User:
    user = User(
        email=f"mute-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _mute(db, user: User, type_: NotificationType) -> None:
    await notify_service.set_prefs(db, user.id, muted_types=[type_], email_digest=True)


async def _count(db, user: User, type_: NotificationType) -> int:
    rows = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.type == type_.value)
    )
    return int(rows.scalar_one())


async def test_automation_notify_action_obeys_the_mute(db):
    """`automation` is created by a direct call from the automation engine, which
    never touches the outbox consumer — the mute used to be checked only there,
    so this checkbox did nothing."""
    from radd.modules.automations.engine import _apply_plan
    from radd.modules.automations.planning import _Plan
    from radd.modules.automations.types import PlanKind

    muted, heard = await _user(db, "Muted"), await _user(db, "Hearing")
    await _mute(db, muted, NotificationType.AUTOMATION)

    for user in (muted, heard):
        await _apply_plan(
            db,
            _Plan(PlanKind.NOTIFY, "notify_user", notify=(user.id, "the build broke")),
            None,
            heard,  # the system actor stand-in: unused by the NOTIFY branch
            rule_name="Ping on breakage",
        )

    assert await _count(db, muted, NotificationType.AUTOMATION) == 0
    # The control: without it, a seam that wrote nothing at all would pass.
    assert await _count(db, heard, NotificationType.AUTOMATION) == 1


async def test_page_update_fan_out_obeys_the_mute(db):
    """`page_updated` is the other direct caller — a synchronous in-request
    fan-out over the page's watchers, again bypassing the consumer."""
    from radd.modules.pages import service as pages, spaces, watchers as page_watchers
    from radd.modules.pages.schemas import PageCreate, PageSpaceCreate, PageUpdate

    author = await _user(db, "Author")
    muted, heard = await _user(db, "Muted"), await _user(db, "Hearing")
    await _mute(db, muted, NotificationType.PAGE_UPDATED)

    slug = f"mute-{uuid.uuid4().hex[:8]}"
    space = await spaces.create_space(db, PageSpaceCreate(name=slug, slug=slug), author.id)
    page = await pages.create_page(
        db, PageCreate(space_id=space.id, title="Runbook", slug="runbook", body="v1"), author.id
    )
    for user in (muted, heard):
        await page_watchers.watch(db, page.id, user.id)

    # The real edit path: update_page fans out to the watchers itself.
    await pages.update_page(db, page.id, PageUpdate(body="v2 — restart order changed"), author.id)

    assert await _count(db, muted, NotificationType.PAGE_UPDATED) == 0
    assert await _count(db, heard, NotificationType.PAGE_UPDATED) == 1


async def test_prefetched_preferences_are_authoritative(db):
    """The consumer's shape: it batch-reads the whole recipient set's preferences
    in one query and hands each row's answer down, so the choke point costs no
    query per notification. A caller that passes nothing gets the lookup — slower,
    never wrong — which is what the two callers above rely on."""
    muted, heard = await _user(db, "Muted"), await _user(db, "Hearing")
    await _mute(db, muted, NotificationType.COMMENTED)

    prefetched = await notify_service.muted_types_by_user(db, [muted.id, heard.id])
    assert prefetched == {muted.id: {NotificationType.COMMENTED.value}}

    for user in (muted, heard):
        await notify_service.create_notification(
            db,
            user_id=user.id,
            type_=NotificationType.COMMENTED,
            event_id=None,
            item_id=None,
            actor_id=None,
            payload={},
            muted_types=prefetched.get(user.id, ()),
        )

    assert await _count(db, muted, NotificationType.COMMENTED) == 0
    assert await _count(db, heard, NotificationType.COMMENTED) == 1
