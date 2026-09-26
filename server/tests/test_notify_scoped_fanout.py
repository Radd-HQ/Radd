"""Who the consumer collects over the scoped recipient sets (spec 118;
RADD-1053/1056), through real rules, memberships and the real consumer: project
subscribers, page-comment recipients, space subscribers. Every test has a
control — "no notification" is also what a broken consumer produces.
"""

import uuid

from sqlalchemy import select

from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments import service as comments_service
from radd.modules.comments.types import CommentParentType
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.notify import consumer, service as notify_service
from radd.modules.notify.models import Notification
from radd.modules.notify.types import Channel, NotificationType, RuleScope
from radd.modules.pages import service as pages_service, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate, PageUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
from radd.modules.workflow import service as workflow_service

from _factories import make_user


# Recipients are admins: every notification still passes a permission gate
# (`item.read` on the project, `page_access` in the space), and a test whose
# recipients hold nothing would pass by being refused rather than by the rule it
# claims to be about.


async def _rows(db, user: User) -> list[Notification]:
    result = await db.execute(select(Notification).where(Notification.user_id == user.id))
    return list(result.scalars())


async def _kinds(db, user: User) -> set[str]:
    return {row.type for row in await _rows(db, user)}


async def _subscribe(db, user: User, scope: RuleScope, scope_id, *kinds) -> None:
    await notify_service.set_rules(
        db, user.id, [(scope, scope_id, {kind.value: Channel.INBOX.value for kind in kinds})]
    )


async def _at_head(db) -> int:
    """Remember where the stream is, so `_drain` reads only what a test wrote."""
    return await events_service.latest_event_id(db)


async def _drain(db, after: int) -> None:
    """The real dispatcher over this test's events. `consumer._handle`, not
        `_consume`: `_consume` wraps each event in a SAVEPOINT and logs what raises,
        which is how RADD-1056 (a page comment raising KeyError) looked like nobody
        wanting a notification. Here it raises."""
    for event in await events_service.read_after(db, after, 500):
        if event.silent or not consumer.handles(event.event_type):
            continue
        await consumer._handle(db, event, watch_only=False)


# --- item subscriptions -------------------------------------------------------


async def test_a_project_subscriber_hears_about_an_issue_they_do_not_watch(db):
    """The reach spec 118 exists for. Before it, `recipient_ids` was watchers ∪
    participant teams, so "tell me what is arriving in this project" had no
    representation at all — you could only find out by looking."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    subscriber = await make_user(db, role=InstanceRole.ADMIN, name="Subscriber")
    stranger = await make_user(db, role=InstanceRole.ADMIN, name="Stranger")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SU{uuid.uuid4().hex[:4].upper()}", name="Subscribed")
    )
    await _subscribe(db, subscriber, RuleScope.PROJECT, project.id, NotificationType.CREATED)

    head = await _at_head(db)
    await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Printer on fire"), actor
    )
    await db.flush()
    await _drain(db, head)

    assert await _kinds(db, subscriber) == {NotificationType.CREATED.value}
    # The control: an identical account with no subscription hears nothing, so
    # the row above is the rule and not a fan-out that reaches everybody.
    assert await _rows(db, stranger) == []


async def test_a_subscriber_who_asked_for_nothing_is_told_nothing(db):
    """A subscription row is not a firehose. `created` is on; `updated` is not
    mentioned, so it falls through to the subscription scope's `off` default —
    which is what keeps a sparse rule from meaning "everything"."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    subscriber = await make_user(db, role=InstanceRole.ADMIN, name="Subscriber")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SP{uuid.uuid4().hex[:4].upper()}", name="Sparse")
    )
    await _subscribe(db, subscriber, RuleScope.PROJECT, project.id, NotificationType.CREATED)
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Printer on fire"), actor
    )

    head = await _at_head(db)
    await items_service.update_item(db, item.id, ItemUpdate(title="Printer still on fire"), actor)
    await db.flush()
    await _drain(db, head)

    assert await _rows(db, subscriber) == []


async def test_the_generic_update_reaches_a_subscriber_who_asked_for_it(db):
    """The other half of the same rule, and the control for the test above: the
    same event, the same person, one cell different."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    subscriber = await make_user(db, role=InstanceRole.ADMIN, name="Subscriber")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"UP{uuid.uuid4().hex[:4].upper()}", name="Updates")
    )
    await _subscribe(db, subscriber, RuleScope.PROJECT, project.id, NotificationType.UPDATED)
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Printer on fire"), actor
    )

    head = await _at_head(db)
    await items_service.update_item(db, item.id, ItemUpdate(title="Printer still on fire"), actor)
    await db.flush()
    await _drain(db, head)

    (row,) = await _rows(db, subscriber)
    assert row.type == NotificationType.UPDATED.value
    # Which fields moved — a generic edit line with no field names is a line
    # carrying no information.
    assert row.payload["fields"] == ["title"]


async def test_the_my_teams_column_follows_the_items_team(db):
    """`teams` is scoped to nothing on purpose: "my teams" is whatever they are
    today, so the rule is matched by intersecting the ITEM's team members with
    everyone who has opted into the column. A subscription to one named team
    could not express "and the ones I join next year"."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    member = await make_user(db, role=InstanceRole.ADMIN, name="Member")
    outsider = await make_user(db, role=InstanceRole.ADMIN, name="Outsider")
    team = await teams_service.create_team(db, TeamCreate(name=f"Desk {uuid.uuid4().hex[:6]}"))
    await teams_service.add_team_member(db, team.id, member.id)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"TM{uuid.uuid4().hex[:4].upper()}", name="Team scope")
    )
    for user in (member, outsider):
        await notify_service.set_rules(
            db,
            user.id,
            [(RuleScope.TEAMS, None, {NotificationType.CREATED.value: Channel.INBOX.value})],
        )

    head = await _at_head(db)
    await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="Printer on fire", team_id=team.id),
        actor,
    )
    await db.flush()
    await _drain(db, head)

    assert await _kinds(db, member) == {NotificationType.CREATED.value}
    # The control: same rule, not in the team. The column is about the item's
    # team field, not about being on some team somewhere.
    assert await _rows(db, outsider) == []


# --- the `own` audience: the one widening this spec makes ---------------------
#
# Spec 118 puts the assignee and the reporter into the AMBIENT audience
# unconditionally. Before it, the ambient set was watchers ∪ participant-team
# members and nothing else — an assignee heard about their own issue because
# being assigned auto-WATCHES, not because they were the assignee, and the two
# are only the same thing while nobody unwatches and every item was created here.
#
# That is a deliberate change and the `own` column is its control surface, which
# is exactly why it is pinned rather than left to be rediscovered as a bug
# report: "I unwatched this and it kept mailing me" and "we imported from Jira
# and everyone's mail volume went up" are the two ways it will be met.


async def _assigned_item(db, actor: User, assignee: User, name: str):
    """An assigned item whose CREATE event is never drained — the shape a silent
        import leaves: the consumer skips silent events, so the item has an assignee
        and reporter but NO watcher rows."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"OW{uuid.uuid4().hex[:4].upper()}", name=name)
    )
    item = await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="Printer on fire", assignee_id=assignee.id),
        actor,
    )
    await db.flush()
    return project, item


async def test_an_assignee_who_watches_nothing_hears_about_their_own_item(db):
    """The widening: only the assignee field connects this person to the issue.
        `commented` defaults to `both` in `own`, so this is the immediate mailer's
        queue — on an imported instance, more mail on the first comment after the
        upgrade."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    assignee = await make_user(db, role=InstanceRole.ADMIN, name="Assignee")
    stranger = await make_user(db, role=InstanceRole.ADMIN, name="Stranger")
    _project, item = await _assigned_item(db, actor, assignee, "Own scope")

    head = await _at_head(db)
    await comments_service.create_comment(
        db, item.id, CommentCreate(body="Any update on this?"), actor
    )
    await db.flush()
    await _drain(db, head)

    assert assignee.id not in await notify_service.watcher_ids(db, item.id)
    (row,) = await _rows(db, assignee)
    assert row.type == NotificationType.COMMENTED.value
    assert row.inbox is True and row.email is True
    # The control: an identical account with no relation to the item hears
    # nothing, so the row above is the `own` set and not a fan-out to everybody.
    assert await _rows(db, stranger) == []


async def test_a_state_change_reaches_them_the_same_way(db):
    """The other ambient kind an assignee cares about, through the same set —
    inbox-only by default, which is the RADD-686 channel for it."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    assignee = await make_user(db, role=InstanceRole.ADMIN, name="Assignee")
    project, item = await _assigned_item(db, actor, assignee, "State scope")
    states = await workflow_service.list_states(db, project.id)
    target = next(state for state in states if state.id != item.state.id)

    head = await _at_head(db)
    await items_service.update_item(db, item.id, ItemUpdate(state_id=target.id), actor)
    await db.flush()
    await _drain(db, head)

    (row,) = await _rows(db, assignee)
    assert row.type == NotificationType.STATE_CHANGED.value
    assert row.inbox is True and row.email is False


async def test_the_own_column_is_the_off_switch_for_all_of_it(db):
    """The half that makes the widening a feature rather than a regression.

    Under RADD-686 there was one answer per type for the whole instance, so
    Unwatch was the only lever an assignee had. Spec 118 replaces the lever: the
    `own` column says it, and it says it whether or not they ever watched."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    assignee = await make_user(db, role=InstanceRole.ADMIN, name="Assignee")
    _project, item = await _assigned_item(db, actor, assignee, "Silenced")
    await notify_service.set_rules(
        db,
        assignee.id,
        [(RuleScope.OWN, None, {NotificationType.COMMENTED.value: Channel.OFF.value})],
    )

    head = await _at_head(db)
    await comments_service.create_comment(
        db, item.id, CommentCreate(body="Any update on this?"), actor
    )
    await db.flush()
    await _drain(db, head)

    assert await _rows(db, assignee) == []


async def test_unwatching_no_longer_silences_an_assignee_and_own_off_still_does(db):
    """Unwatch removes the PARTICIPATING relation only — `own` still applies. Both
        halves in one test because the first alone reads like a bug and the second
        answers it: the same person and item, one rule row apart."""
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    assignee = await make_user(db, role=InstanceRole.ADMIN, name="Assignee")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"UW{uuid.uuid4().hex[:4].upper()}", name="Unwatched")
    )
    head = await _at_head(db)
    item = await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="Printer on fire", assignee_id=assignee.id),
        actor,
    )
    await db.flush()
    await _drain(db, head)
    assert assignee.id in await notify_service.watcher_ids(db, item.id)
    await notify_service.unwatch(db, item.id, assignee.id)

    head = await _at_head(db)
    await comments_service.create_comment(db, item.id, CommentCreate(body="Still?"), actor)
    await db.flush()
    await _drain(db, head)

    assert NotificationType.COMMENTED.value in await _kinds(db, assignee)

    # …and with the `own` column off as well, silence. Same person, same
    # unwatched item, one rule row apart.
    await notify_service.set_rules(
        db,
        assignee.id,
        [(RuleScope.OWN, None, {NotificationType.COMMENTED.value: Channel.OFF.value})],
    )
    before = len(await _rows(db, assignee))
    head = await _at_head(db)
    await comments_service.create_comment(db, item.id, CommentCreate(body="And now?"), actor)
    await db.flush()
    await _drain(db, head)

    assert len(await _rows(db, assignee)) == before


# --- pages (RADD-1056 + the space subscription) -------------------------------


async def _space_with_page(db, actor: User):
    slug = f"fan-{uuid.uuid4().hex[:8]}"
    space = await spaces.create_space(db, PageSpaceCreate(name=slug, slug=slug), actor.id)
    page = await pages_service.create_page(
        db,
        PageCreate(space_id=space.id, title="Runbook", slug="runbook", body="v1"),
        actor.id,
    )
    return space, page


async def test_a_page_comment_notifies_the_pages_watchers(db):
    """RADD-1056: comments are polymorphic, but the consumer read
        `payload["item"]["id"]` unconditionally, so every page comment raised inside
        the per-event savepoint, was logged and skipped — zero notifications, while
        `page_updated` made the wiki look alive."""
    author = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    watcher = await make_user(db, role=InstanceRole.ADMIN, name="Watcher")
    _space, page = await _space_with_page(db, author)
    from radd.modules.pages import watchers as page_watchers

    await page_watchers.watch(db, page.id, watcher.id)

    head = await _at_head(db)
    await comments_service.create_comment(
        db,
        page.id,
        CommentCreate(body="This is out of date."),
        author,
        entity_type=CommentParentType.PAGE.value,
    )
    await db.flush()
    await _drain(db, head)

    (row,) = await _rows(db, watcher)
    assert row.type == NotificationType.COMMENTED.value
    assert row.item_id is None  # a page comment has no issue to hang off
    assert row.payload["page_slug"] == "runbook"
    assert row.payload["title"] == "Runbook"
    assert row.payload["excerpt"] == "This is out of date."


async def test_a_page_comment_that_names_someone_reaches_them(db):
    """The part of RADD-1056 that reads worst: an @-mention on a wiki page went
    to nobody, and the person who wrote it had every reason to believe it had."""
    author = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    named = await make_user(db, role=InstanceRole.ADMIN, name="Named")
    _space, page = await _space_with_page(db, author)

    head = await _at_head(db)
    await comments_service.create_comment(
        db,
        page.id,
        CommentCreate(body=f"@[{named.name}]({named.id}) can you confirm the restart order?"),
        author,
        entity_type=CommentParentType.PAGE.value,
    )
    await db.flush()
    await _drain(db, head)

    (row,) = await _rows(db, named)
    assert row.type == NotificationType.MENTIONED.value
    assert row.payload["source"] == "comment"


async def test_a_space_subscriber_hears_about_a_new_page(db):
    """`page.created` notified NOBODY before spec 118 — the synchronous fan-out
    was wired to `update_page` alone, so a wiki could gain a page and no watcher
    of anything would learn it existed."""
    author = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    subscriber = await make_user(db, role=InstanceRole.ADMIN, name="Subscriber")
    stranger = await make_user(db, role=InstanceRole.ADMIN, name="Stranger")
    slug = f"fan-{uuid.uuid4().hex[:8]}"
    space = await spaces.create_space(db, PageSpaceCreate(name=slug, slug=slug), author.id)
    await _subscribe(
        db, subscriber, RuleScope.SPACE, space.id, NotificationType.PAGE_CREATED
    )

    head = await _at_head(db)
    await pages_service.create_page(
        db,
        PageCreate(space_id=space.id, title="Colour pipeline", slug="colour", body="draft"),
        author.id,
    )
    await db.flush()
    await _drain(db, head)

    (row,) = await _rows(db, subscriber)
    assert row.type == NotificationType.PAGE_CREATED.value
    assert row.payload["space_slug"] == slug and row.payload["page_slug"] == "colour"
    assert await _rows(db, stranger) == []


async def test_a_page_edit_reaches_a_space_subscriber_who_never_watched_it(db):
    """The wiki's ambient half. A watcher hears about the page they clicked
    Watch on; a space subscriber hears about the space, which is the only way to
    follow a wiki that is still being written."""
    author = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    subscriber = await make_user(db, role=InstanceRole.ADMIN, name="Subscriber")
    space, page = await _space_with_page(db, author)
    await _subscribe(
        db, subscriber, RuleScope.SPACE, space.id, NotificationType.PAGE_UPDATED
    )

    head = await _at_head(db)
    await pages_service.update_page(
        db, page.id, PageUpdate(body="v2 — restart order changed"), author.id
    )
    await db.flush()
    await _drain(db, head)

    (row,) = await _rows(db, subscriber)
    assert row.type == NotificationType.PAGE_UPDATED.value
    assert row.payload["version"] == 2


async def test_a_page_notification_is_refused_to_someone_who_cannot_read_the_page(db):
    """A watch does not outlive a space restriction: a non-admin with no grant in
        the space holds no `page.read`, so the notification is refused; the admin
        beside them is the control that the fan-out ran at all."""
    author = await make_user(db, role=InstanceRole.ADMIN, name="Ada Agent")
    outsider = await make_user(db, name="Outsider")
    insider = await make_user(db, role=InstanceRole.ADMIN, name="Insider")
    _space, page = await _space_with_page(db, author)
    from radd.modules.pages import watchers as page_watchers

    for user in (outsider, insider):
        await page_watchers.watch(db, page.id, user.id)

    head = await _at_head(db)
    await pages_service.update_page(db, page.id, PageUpdate(body="v2"), author.id)
    await db.flush()
    await _drain(db, head)

    assert await _rows(db, outsider) == []
    assert await _kinds(db, insider) == {NotificationType.PAGE_UPDATED.value}
