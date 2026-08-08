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

RADD-978's section is DB-backed for the same reason twice over: what was missing
was that the consumer never HANDLED `item.participant_added`, and what makes the
recipient allowed to hear about it is the participant row itself. Neither is
visible to a pure planner test or to a hand-built event, so those tests drive the
real `participants.add_participant` and the real consumer.
"""

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
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
    types as notify_types,
)
from radd.modules.notify.models import Notification
from radd.modules.participants import service as participants
from radd.modules.participants.schemas import ParticipantAdd
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
# The endpoint itself, not the module: `notify.router` is the APIRouter object
# the package re-exports, which shadows the module of that name.
from radd.modules.notify.router import put_preferences
from radd.modules.notify.schemas import NotificationPrefsUpdate
from radd.modules.notify.types import (
    CONSUMER_NAME,
    DEFAULT_EMAIL_TYPES,
    NotificationType,
    default_email_type_values,
    default_email_types,
)

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


# --- the system actor is not a person (RADD-996) ---


def test_the_notify_copy_of_the_system_actor_id_matches_the_engines():
    """`notify.types` keeps its own literal so `planner.py` imports no module at
    all (and notify's dependency list stays the spine). This is the pin that
    makes that safe — the whole risk of the wire-constant idiom is drift, and it
    is the risk the four constants above carry with nothing checking them."""
    assert notify_types.SYSTEM_ACTOR_ID == SYSTEM_ACTOR_ID


def test_an_item_created_by_the_system_actor_watches_nobody():
    """RADD-996: mail intake creates items AS the system actor, so auto-watching
    the creator put `automation@radd.system` on the watcher list of every ticket
    that has ever arrived by email — and a human replying then fanned a
    `commented` row to a robot, which the mailer tried to deliver to an address
    that does not receive. The reporter arm is asserted in the same breath
    because an intake-created item whose sender matched no account has none, and
    one whose sender matched the system actor would have the same problem."""
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
        frozenset(),
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
    await notify_service.set_prefs(
        db,
        user.id,
        muted_types=[type_],
        email_types=default_email_types(),  # the defaults, untouched by the mute
        email_digest=True,
    )


def _load_migration(name: str):
    """Import one revision file by name — `migrations/` is a script directory,
    not a package, so there is nothing to import normally."""
    path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    """RADD-996's cleanup decision, asserted rather than described.

    `item_watchers` already holds a system-actor row on every ticket that
    arrived by email, and no migration removes them — rows nobody displays are
    not worth a destructive write. What makes leaving them free is the refusal
    at the write choke point: they can go on being planned from and produce
    nothing. Driven through the same seam the mute uses, for the same reason —
    it is the one function every producer of a notification calls.
    """
    author = await _user(db, "Author")
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


# --- participant_added, end to end (RADD-978) ---------------------------------
#
# The planner tests above are pure, so they cannot see the two things that were
# actually broken: the consumer did not HANDLE `item.participant_added` at all,
# and the recipient has no standing in the project until the participant row
# exists. Both only answer when the real `participants.add_participant` writes
# the row, emits the real event, and the real consumer reads it — so that is
# what these drive. A hand-built event would have proved neither.


async def _admin(db, name: str) -> User:
    """Someone who can share an item — `add_participant` wants item.update or
    the reporter's identity."""
    user = User(
        email=f"share-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


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
    """The gap RADD-978 closes: the add auto-watched them, so every LATER event
    reached them and the add itself reached nobody.

    The recipient holds nothing on the project — no role grant, just an account.
    They pass the consumer's per-row read gate through the Baseline's
    `item.read@participant`, i.e. through the very row that is being announced.
    """
    actor = await _admin(db, "Ada Agent")
    project, item = await _shareable_item(db, actor)
    colleague = await _user(db, "Colleague")

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
    actor = await _admin(db, "Ada Agent")
    _project, item = await _shareable_item(db, actor)
    member = await _user(db, "Team Member")
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
    actor = await _admin(db, "Ada Agent")
    _project, item = await _shareable_item(db, actor)

    await _share(db, item, actor, user_id=actor.id)

    assert await _rows(db, actor) == []


async def test_muting_participant_added_silences_it(db):
    """The mute is enforced inside `create_notification` (RADD-971), so this type
    inherited it the moment it was created through that seam. The control user is
    the point: without one, "no row" could equally mean the consumer never ran."""
    actor = await _admin(db, "Ada Agent")
    _project, item = await _shareable_item(db, actor)
    muted, heard = await _user(db, "Muted"), await _user(db, "Hearing")
    await _mute(db, muted, NotificationType.PARTICIPANT_ADDED)

    await _share(db, item, actor, user_id=muted.id)
    await _share(db, item, actor, user_id=heard.id)

    assert await _rows(db, muted) == []
    assert await _count(db, heard, NotificationType.PARTICIPANT_ADDED) == 1


# --- the channel matrix (RADD-686) --------------------------------------------


async def test_muting_a_type_drops_it_from_the_email_column_on_save(db):
    """Email requires inbox, and the SERVER says so rather than trusting the UI.

    "Email me about comments, but never raise a comment notification" is not a
    conflict needing a 422 — a muted type never becomes a row and rows are what
    get mailed, so the request has exactly one coherent meaning and `set_prefs`
    stores it. The PUT response is read back off the row for the same reason: a
    raw API caller has to be able to see what was kept.
    """
    user = await _user(db, "Contradictory")

    result = await put_preferences(
        NotificationPrefsUpdate(
            muted_types=[NotificationType.COMMENTED],
            email_types=[NotificationType.COMMENTED, NotificationType.MENTIONED],
            email_digest=True,
        ),
        db,
        user,
    )

    assert result.muted_types == [NotificationType.COMMENTED]
    assert result.email_types == [NotificationType.MENTIONED]
    # The stored row, not just the reply — the mailer reads the column.
    prefs = await notify_service.get_prefs(db, user.id)
    assert prefs.email_types == [NotificationType.MENTIONED.value]


async def test_a_user_with_no_prefs_row_resolves_to_the_default_email_set(db):
    """The mailer's seam returns an answer for EVERY id it is asked about,
    because absent means `DEFAULT_EMAIL_TYPES` — not the empty set that a
    `.get(id, ())` over a partial dict (the shape `muted_types_by_user` uses,
    where absent really does mean none) would have silently produced."""
    saved, never = await _user(db, "Saved"), await _user(db, "Never saved")
    await notify_service.set_prefs(
        db, saved.id, muted_types=[], email_types=[NotificationType.APPROVAL], email_digest=True
    )

    resolved = await notify_service.email_types_by_user(db, [saved.id, never.id])

    assert resolved[saved.id] == frozenset({NotificationType.APPROVAL.value})
    assert resolved[never.id] == frozenset(type_.value for type_ in DEFAULT_EMAIL_TYPES)


async def test_the_migration_backfills_existing_rows_with_its_frozen_default_set(db):
    """A preferences row saved before RADD-686 must come out of the migration
    with the DEFAULT set, not an empty one: everyone who had ever saved a
    preference already got comment mail, and `[]` would silence a channel they
    never turned off.

    What it is compared against is the migration's OWN frozen literal, not
    `default_email_type_values()`. This assertion used to read the live constant,
    and RADD-978 is what showed why it cannot: adding `participant_added` to
    `DEFAULT_EMAIL_TYPES` failed a test about a backfill that ran months earlier.
    A migration keeps meaning what it meant the day it ran; the accepted
    consequence (stated in `notify.types`) is that the two drift apart by exactly
    the types added since, which is asserted below rather than hidden.

    The suite's database is created at head, so there are no legacy rows to
    observe — the only honest way to test the backfill is to run it. The column
    is dropped, a pre-RADD-686 row is written, and the migration's own
    `upgrade()` is replayed through alembic's operations proxy. All of it inside
    the test transaction, which rolls the DDL back too (Postgres DDL is
    transactional), so no other test sees a table mid-migration.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = _load_migration("d686emailtypes_notification_email_channel_per_type")
    user_id = uuid.uuid4()
    await db.execute(text("ALTER TABLE notification_prefs DROP COLUMN email_types"))
    await db.execute(
        text(
            "INSERT INTO notification_prefs (user_id, muted_types, email_digest) "
            "VALUES (:user_id, '[]'::jsonb, true)"
        ),
        {"user_id": user_id},
    )

    def _upgrade(connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    await db.run_sync(lambda session: _upgrade(session.connection()))

    stored = await db.execute(
        text("SELECT email_types FROM notification_prefs WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    frozen = json.loads(migration._DEFAULT_EMAIL_TYPES)
    assert stored.scalar_one() == frozen
    # And the drift is a strict subset, in one direction only: every type the
    # backfill wrote is still a default, and `participant_added` (RADD-978, no
    # migration by decision) is the one a pre-existing row does not carry.
    assert set(frozen) < {type_.value for type_ in DEFAULT_EMAIL_TYPES}
    assert NotificationType.PARTICIPANT_ADDED.value not in frozen
    assert NotificationType.PARTICIPANT_ADDED.value in default_email_type_values()
    # The default is dropped afterwards on purpose: the policy lives in
    # `notify.types`, and a copy left in the schema is a second source of truth.
    remaining = await db.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'notification_prefs' AND column_name = 'email_types'"
        )
    )
    assert remaining.scalar_one() is None
