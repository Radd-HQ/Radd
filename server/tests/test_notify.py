"""Notify planning (spec 26) and the delivery choke point (RADD-971). The planner
tests are pure: no self-notification, one notification per user per event with
personal types beating ambient ones, auto-watch, the mention grammar. The
DB-backed sections exist because the mute is enforced at the WRITE
(`service.create_notification`) and `item.participant_added` is handled by the
real consumer — neither is visible to a pure planner test.
"""

import uuid

from sqlalchemy import func, select

from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.notify import (
    consumer,
    planner,
    service as notify_service,
)
from radd.modules.notify.models import Notification
from radd.modules.participants import service as participants
from radd.modules.participants.schemas import ParticipantAdd
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
from radd.modules.notify.types import (
    CONSUMER_NAME,
    RELATIONSHIP_SCOPES,
    Channel,
    NotificationType,
    RuleScope,
)

from _factories import make_user

ACTOR = uuid.uuid4()
ASSIGNEE = uuid.uuid4()
WATCHER = uuid.uuid4()
MENTIONED = uuid.uuid4()
REPORTER = uuid.uuid4()


def _types_by_user(plan: planner.Plan) -> dict[uuid.UUID, NotificationType]:
    return {p.user_id: p.type for p in plan.notifications}


def _watching(*user_ids: uuid.UUID) -> planner.Audience:
    """An audience of plain WATCHERS — the only kind that existed before spec
    118, and the one every planner test below is about. Spelling it out keeps
    the ambient-vs-personal precedence tests readable while the other three sets
    are exercised where they are built (`consumer.item_audience`)."""
    return planner.Audience(participating=frozenset(user_ids))


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
    plan = planner.plan_item_updated(payload, ACTOR, _watching(WATCHER, ACTOR), frozenset())
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
    plan = planner.plan_item_updated(payload, ACTOR, _watching(ASSIGNEE, WATCHER), frozenset())
    assert _types_by_user(plan) == {
        ASSIGNEE: NotificationType.ASSIGNED,
        WATCHER: NotificationType.STATE_CHANGED,
    }


def test_an_edit_with_no_semantic_type_plans_the_generic_one():
    """A title change is planned as `updated`, carrying which fields moved.
    Whether anyone HEARS it is the resolver's (default `off` in every relationship
    scope) — that silence is tested in test_notify_rules.py, not here."""
    payload = {"item": {"assignee": None}, "changes": [{"field": "title", "from": "a", "to": "b"}]}
    plan = planner.plan_item_updated(payload, ACTOR, _watching(WATCHER), frozenset())
    assert _types_by_user(plan) == {WATCHER: NotificationType.UPDATED}
    assert plan.notifications[0].detail == {"fields": ["title"]}
    assert plan.notifications[0].relation.is_participating is True
    assert plan.watch == set()


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
    plan = planner.plan_item_updated(payload, ACTOR, planner.Audience(), frozenset())
    assert plan.watch == {REPORTER}
    assert plan.notifications == []


def test_update_untouched_reporter_is_not_rewatched():
    # The snapshot always carries the reporter; only a `reporter` CHANGE watches
    # them (an unwatch must stick when unrelated fields move).
    payload = {
        "item": {"assignee": None, "reporter": {"id": str(REPORTER), "name": "R"}},
        "changes": [{"field": "title", "from": "a", "to": "b"}],
    }
    plan = planner.plan_item_updated(payload, ACTOR, planner.Audience(), frozenset())
    assert plan.watch == set()


# --- the system actor is not a person (RADD-996) ---


def test_an_item_created_by_the_system_actor_watches_nobody():
    """RADD-996: mail intake creates items AS the system actor, which must not
    auto-watch (a reply would fan a `commented` row to a robot). The reporter arm
    is asserted too: a sender matching the system actor has the same problem."""
    payload = {
        "item": {
            "assignee": None,
            "reporter": {"id": str(SYSTEM_ACTOR_ID), "name": "Automation"},
        }
    }
    plan = planner.plan_item_created(payload, SYSTEM_ACTOR_ID, frozenset())
    assert plan.watch == set()
    assert plan.notifications == []


def test_a_comment_posted_by_the_system_actor_watches_nobody():
    """The other half, and the one the live incident actually ran through: an
    emailed REPLY is posted as the system actor too, so the comment author
    auto-watch is a second door onto the same watcher row."""
    plan = planner.plan_comment_created(
        {"excerpt": "the customer replied", "visibility": "public"},
        SYSTEM_ACTOR_ID,
        planner.Audience(),
        frozenset(),
    )
    assert plan.watch == set()


def test_a_real_person_is_still_watched_when_the_system_actor_is_around():
    """The control: the guard is about one identity, not about automation. An
    item the engine creates and assigns to a person still follows that person."""
    payload = {"item": {"assignee": {"id": str(ASSIGNEE), "name": "A"}}}
    plan = planner.plan_item_created(payload, SYSTEM_ACTOR_ID, frozenset())
    assert plan.watch == {ASSIGNEE}
    assert _types_by_user(plan) == {ASSIGNEE: NotificationType.ASSIGNED}


# --- comment created ---


def test_comment_notifies_watchers_and_mentions_win():
    payload = {"excerpt": "hey", "visibility": "public"}
    plan = planner.plan_comment_created(
        payload, ACTOR, _watching(WATCHER, MENTIONED, ACTOR), frozenset({MENTIONED})
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
    plan = planner.plan_comment_created(payload, ACTOR, _watching(WATCHER), frozenset())
    assert plan.notifications[0].detail["visibility"] == "internal"


# --- participant added (RADD-978) ---


def test_participant_added_notifies_the_added_user():
    added = uuid.uuid4()
    plan = planner.plan_participant_added(
        {"user": {"id": str(added), "name": "Ada"}, "team": None}, ACTOR
    )
    assert _types_by_user(plan) == {added: NotificationType.PARTICIPANT_ADDED}
    # The write path already watched them (`participants.add_participant` calls
    # `notify.add_watchers`); a second mechanism here would agree only by luck.
    assert plan.watch == set()


def test_participant_added_plans_nothing_for_a_team():
    """A team row resolves to CURRENT members at fan-out time, so there is no
    stable set to address — and the membership is ambient, not personal."""
    plan = planner.plan_participant_added(
        {"user": None, "team": {"id": str(uuid.uuid4()), "name": "Desk"}}, ACTOR
    )
    assert plan.notifications == [] and plan.watch == set()


def test_participant_added_never_notifies_the_actor():
    plan = planner.plan_participant_added({"user": {"id": str(ACTOR), "name": "A"}}, ACTOR)
    assert plan.notifications == []


# --- the mute is enforced at the write, so every producer inherits it (RADD-971) ---


async def _mute(db, user: User, type_: NotificationType) -> None:
    """Turn one kind OFF for this person in every relationship scope (spec 118's
    rules are per scope). These tests are about the choke point, not precedence."""
    await notify_service.set_rules(
        db,
        user.id,
        [
            (scope, None, {type_.value: Channel.OFF.value})
            for scope in RELATIONSHIP_SCOPES
        ],
    )


async def _count(db, user: User, type_: NotificationType) -> int:
    rows = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.type == type_.value)
    )
    return int(rows.scalar_one())


async def _rows(db, user: User) -> list[Notification]:
    rows = await db.execute(select(Notification).where(Notification.user_id == user.id))
    return list(rows.scalars())


async def test_the_system_actor_is_refused_a_notification_row(db):
    """RADD-996: existing system-actor watcher rows are left in place, which is
    free only because the write choke point (the one function every producer
    calls) refuses the system actor a notification row."""
    author = await make_user(db, name="Author")
    item_id = uuid.uuid4()  # `notifications.item_id` carries no FK
    created = await notify_service.create_notification(
        db,
        user_id=SYSTEM_ACTOR_ID,
        type_=NotificationType.COMMENTED,
        event_id=None,
        item_id=item_id,
        actor_id=author.id,
        payload={"excerpt": "any update?"},
    )

    assert created is None
    rows = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.item_id == item_id)
    )
    assert rows.scalar_one() == 0
    # The control: the same call for a real person writes the row.
    assert await notify_service.create_notification(
        db,
        user_id=author.id,
        type_=NotificationType.COMMENTED,
        event_id=None,
        item_id=item_id,
        actor_id=author.id,
        payload={"excerpt": "any update?"},
    ) is not None


async def test_automation_notify_action_obeys_the_mute(db):
    """`automation` is created by a direct call from the automation engine, which
    never touches the outbox consumer — the mute used to be checked only there,
    so this checkbox did nothing."""
    from radd.modules.automations.engine import _apply_plan
    from radd.modules.automations.planning import _Plan
    from radd.modules.automations.types import PlanKind

    muted, heard = await make_user(db, name="Muted"), await make_user(db, name="Hearing")
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


async def test_an_automation_notification_carries_the_issue_it_fired_on(db):
    """RADD-972: renderers compose the line from the PAYLOAD, so the item ref must
    be resolved into it at write time like every other item-scoped type; an
    itemless rule keeps the linkless line."""
    from radd.modules.automations.engine import _apply_plan
    from radd.modules.automations.planning import _Plan
    from radd.modules.automations.types import PlanKind
    from radd.modules.items.models import WorkItem
    from radd.modules.notify import lines

    actor = User(
        email=f"target-{uuid.uuid4().hex[:8]}@example.com",
        name="Automation target",
        instance_role=InstanceRole.ADMIN.value,  # may create the item it is told about
    )
    db.add(actor)
    await db.flush()
    project, created = await _shareable_item(db, actor)
    item = await db.get(WorkItem, created.id)
    key = f"{project.key}-{created.number}"

    for target in (item, None):
        await _apply_plan(
            db,
            _Plan(PlanKind.NOTIFY, "notify_user", notify=(actor.id, "Escalated to tier 2")),
            target,
            actor,
            rule_name="Escalate",
        )

    rows = await _rows(db, actor)
    assert len(rows) == 2
    with_item = next(row for row in rows if row.item_id == created.id)
    without = next(row for row in rows if row.item_id is None)
    assert with_item.payload["item_key"] == key
    assert with_item.payload["item_title"] == "Printer on fire"
    assert with_item.payload["message"] == "Escalated to tier 2"
    assert "item_key" not in without.payload

    linked = lines.entry(with_item, {})
    assert linked.url.endswith(f"/issues/{key}")
    assert linked.subject == f"[{key}] Printer on fire"
    assert lines.entry(without, {}).url == ""


async def test_page_update_fan_out_obeys_the_channel_rules(db):
    """The wiki path through the outbox (spec 118): the real edit, then the real
    consumer — a page edit that reaches nobody looks identical to one whose
    recipients were all silenced. Both watchers are ADMINS because the fan-out
    checks `page_access` per recipient; bare accounts would pass for the wrong
    reason."""
    from radd.modules.pages import service as pages, spaces, watchers as page_watchers
    from radd.modules.pages.schemas import PageCreate, PageSpaceCreate, PageUpdate

    author = await make_user(db, role=InstanceRole.ADMIN, name="Author")
    muted, heard = (
        await make_user(db, role=InstanceRole.ADMIN, name="Muted"),
        await make_user(db, role=InstanceRole.ADMIN, name="Hearing"),
    )
    await _mute(db, muted, NotificationType.PAGE_UPDATED)

    slug = f"mute-{uuid.uuid4().hex[:8]}"
    space = await spaces.create_space(db, PageSpaceCreate(name=slug, slug=slug), author.id)
    page = await pages.create_page(
        db, PageCreate(space_id=space.id, title="Runbook", slug="runbook", body="v1"), author.id
    )
    for user in (muted, heard):
        await page_watchers.watch(db, page.id, user.id)

    head = await events_service.latest_event_id(db)
    await pages.update_page(db, page.id, PageUpdate(body="v2 — restart order changed"), author.id)
    await db.flush()
    # `_handle`, not `_consume`: the latter swallows (a SAVEPOINT + a log line),
    # and here a raise should fail the test. Routing is still proved — the
    # filter below is the consumer's own `handles`, so a page event its subject
    # provider does not claim would be skipped here exactly as in production.
    for event in await events_service.read_after(db, head, 100):
        if consumer.handles(event.event_type):
            await consumer._handle(db, event, watch_only=False)

    assert await _count(db, muted, NotificationType.PAGE_UPDATED) == 0
    (row,) = await _rows(db, heard)
    assert row.type == NotificationType.PAGE_UPDATED.value
    # Page context resolved at WRITE time, so the inbox row links without a join
    # — and the space slug is there because the EVENT carries a `page_space`
    # subject now, not because this file went and looked it up.
    assert row.item_id is None
    assert row.payload["space_slug"] == slug
    assert row.payload["page_slug"] == "runbook"
    assert row.payload["title"] == "Runbook"
    assert row.payload["actor_name"] == "Author"


async def test_prefetched_rules_are_authoritative(db):
    """The consumer batch-reads every recipient's rules and hands each answer down;
    a caller passing nothing gets the lookup. The prefetch answers for EVERY id,
    empty included: an explicit empty `RuleSet` resolves to the documented
    defaults, where a partial dict read with `.get` nearly stored "email nothing"
    (RADD-686)."""
    muted, heard = await make_user(db, name="Muted"), await make_user(db, name="Hearing")
    await _mute(db, muted, NotificationType.COMMENTED)

    prefetched = await notify_service.rules_by_user(db, [muted.id, heard.id])
    assert set(prefetched) == {muted.id, heard.id}
    assert prefetched[heard.id].rows == ()
    assert prefetched[muted.id].get(RuleScope.PARTICIPATING).channels == {
        NotificationType.COMMENTED.value: Channel.OFF.value
    }

    for user in (muted, heard):
        await notify_service.create_notification(
            db,
            user_id=user.id,
            type_=NotificationType.COMMENTED,
            event_id=None,
            item_id=None,
            actor_id=None,
            payload={},
            rules=prefetched.get(user.id),
        )

    assert await _count(db, muted, NotificationType.COMMENTED) == 0
    assert await _count(db, heard, NotificationType.COMMENTED) == 1


# --- participant_added, end to end (RADD-978) ---------------------------------
#
# The planner tests above are pure, so they cannot see the two things that were
# actually broken: the consumer did not HANDLE `item.participant_added` at all,
# and the recipient has no standing in the project until the participant row
# exists. Both only answer when the real `participants.add_participant` writes
# the row, emits the real event, and the real consumer reads it — so that is
# what these drive. A hand-built event would have proved neither.
# The sharer is an admin: `add_participant` wants item.update or the
# reporter's identity.


async def _shareable_item(db, actor: User):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"PA{uuid.uuid4().hex[:4].upper()}", name="Participants")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Printer on fire"), actor
    )
    return project, item


async def _share(db, item, actor: User, **subject) -> None:
    """One real add, consumed by the real consumer.

    The cursor is parked at the current head first, so the batch this reads is
    exactly the event the add emits — not whatever else the suite has written.
    """
    head = await events_service.latest_event_id(db)
    await events_service.set_offset(db, CONSUMER_NAME, head)
    await participants.add_participant(db, item.id, ParticipantAdd(**subject), actor)
    await db.flush()
    await consumer._consume(db, watch_only=False)


async def test_a_direct_participant_is_told_they_were_added(db):
    """RADD-978: the add itself reaches them. The recipient holds no role on the
    project; they pass the read gate through the Baseline's
    `item.read@participant`, i.e. through the very row being announced."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    project, item = await _shareable_item(db, actor)
    colleague = await make_user(db, name="Colleague")

    await _share(db, item, actor, user_id=colleague.id)

    (row,) = await _rows(db, colleague)
    assert row.type == NotificationType.PARTICIPANT_ADDED.value
    assert row.item_id == item.id and row.actor_id == actor.id
    # Display values resolved at WRITE time, like every other type — a later
    # rename cannot make the inbox row lie about what it told you.
    assert row.payload["item_key"] == f"{project.key}-{item.number}"
    assert row.payload["item_title"] == "Printer on fire"
    assert row.payload["actor_name"] == "Ada Agent"


async def test_adding_a_team_notifies_nobody_personally(db):
    """A team row resolves to CURRENT members at fan-out time (that is what makes
    joining a team join its shared tickets), so there is no stable set to
    address and the membership is ambient by design."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    _project, item = await _shareable_item(db, actor)
    member = await make_user(db, name="Team Member")
    team = await teams_service.create_team(
        db, TeamCreate(name=f"Desk {uuid.uuid4().hex[:6]}")
    )
    await teams_service.add_team_member(db, team.id, member.id)

    await _share(db, item, actor, team_id=team.id)
    assert await _rows(db, member) == []

    # The control: the same person, added DIRECTLY, does get told — so the empty
    # list above is the team rule, not a fan-out that reaches nobody at all.
    await _share(db, item, actor, user_id=member.id)
    assert [row.type for row in await _rows(db, member)] == [
        NotificationType.PARTICIPANT_ADDED.value
    ]


async def test_adding_yourself_as_a_participant_is_silent(db):
    """The actor is never notified about their own action — the invariant every
    other type in this file already holds to."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    _project, item = await _shareable_item(db, actor)

    await _share(db, item, actor, user_id=actor.id)

    assert await _rows(db, actor) == []


async def test_muting_participant_added_silences_it(db):
    """The mute is enforced inside `create_notification` (RADD-971), so this type
    inherited it the moment it was created through that seam. The control user is
    the point: without one, "no row" could equally mean the consumer never ran."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    _project, item = await _shareable_item(db, actor)
    muted, heard = await make_user(db, name="Muted"), await make_user(db, name="Hearing")
    await _mute(db, muted, NotificationType.PARTICIPANT_ADDED)

    await _share(db, item, actor, user_id=muted.id)
    await _share(db, item, actor, user_id=heard.id)

    assert await _rows(db, muted) == []
    assert await _count(db, heard, NotificationType.PARTICIPANT_ADDED) == 1
