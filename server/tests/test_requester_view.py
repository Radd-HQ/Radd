"""The requester's view of a request (RADD-796/797/798).

A requester is admitted by RELATIONSHIP to a row (reported it, or filed for their
team) and holds no `item.read`, so the assertions are about what does NOT come back.
The Baseline is emptied throughout: a floor holding `item.read` would let every
test pass for the wrong reason.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.models import Role
from radd.modules.auth.types import BuiltinRoleKey
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentParentType, CommentVisibility
from radd.modules.forms import (
    portal,
    requests as requests_service,
    service as forms_service,
)
from radd.modules.forms.schemas import (
    FormCreate,
    FormShareEntry,
    FormSharingUpdate,
    FormSubmit,
    FormUpdate,
)
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate

from _factories import make_project, make_user


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        baseline = (
            await session.execute(
                select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value)
            )
        ).scalar_one()
        baseline.permissions = []
        authz.forget_baseline(session)
        yield session
        await session.rollback()
    await engine.dispose()


async def _shared_form(db, admin, project, requester, *, team_picker=False):
    form = await forms_service.create_form(
        db, FormCreate(project_id=project.id, name="Ask for something"), actor=admin
    )
    await forms_service.update_sharing(
        db, form.id, FormSharingUpdate(shares=[FormShareEntry(user_id=requester.id)]), admin
    )
    if team_picker:
        form = await forms_service.update_form(
            db, form.id, FormUpdate(team_picker_enabled=True), actor=admin
        )
    return form


async def _file(db, form, requester, title="A request", team_id=None):
    """Submit, then resolve the item — the portal deliberately returns only a key
    and a title to the submitter, so a test needs the same lookup a caller does."""
    from radd.modules.items import service as items_service

    result = await portal.submit_portal_form(
        db, form.id, FormSubmit(title=title, team_id=team_id), requester
    )
    item = await items_service.find_item_by_key(db, result.key)
    assert item is not None
    # `WorkItem.key` is derived (project key + number), not a column — so carry
    # the key the submit already computed rather than recomputing it here.
    return SimpleNamespace(id=item.id, key=result.key)


# --- the admission rule -------------------------------------------------------


async def test_a_requester_opens_their_own_request(db, admin):
    requester = await make_user(db, name="Requester")
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)
    filed = await _file(db, form, requester, "My laptop is broken")

    detail = await requests_service.get_request(db, requester, filed.key)
    assert detail.title == "My laptop is broken"
    assert detail.key == filed.key


async def test_a_stranger_gets_404_not_403(db, admin):
    """A refusal would confirm the key names a real issue — which is exactly what
    someone guessing keys is trying to learn."""
    requester, stranger = (
        await make_user(db, name="Requester"),
        await make_user(db, name="Stranger"),
    )
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)
    filed = await _file(db, form, requester)

    with pytest.raises(NotFoundError):
        await requests_service.get_request(db, stranger, filed.key)


async def test_a_teammate_opens_a_shared_request(db, admin):
    """RADD-798's decision: sharing with a team means the team can OPEN it."""
    requester, teammate = (
        await make_user(db, name="Requester"),
        await make_user(db, name="Teammate"),
    )
    team = await teams_service.create_team(db, TeamCreate(name=f"T{uuid.uuid4().hex[:6]}"))
    for person in (requester, teammate):
        await teams_service.add_team_member(db, team.id, person.id)
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester, team_picker=True)
    filed = await _file(db, form, requester, team_id=team.id)

    detail = await requests_service.get_request(db, teammate, filed.key)
    assert detail.key == filed.key
    assert detail.team == team.name
    # ...and it appears in the teammate's list even though they did not file it.
    assert filed.key in {r.key for r in await requests_service.list_my_requests(db, teammate)}


async def test_you_cannot_share_with_a_team_you_are_not_in(db, admin):
    """The picker is UI; this is the enforcement."""
    requester = await make_user(db, name="Requester")
    other_team = await teams_service.create_team(
        db, TeamCreate(name=f"Other{uuid.uuid4().hex[:6]}")
    )
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester, team_picker=True)

    with pytest.raises(ConflictError):
        await _file(db, form, requester, team_id=other_team.id)


async def test_a_form_without_the_picker_refuses_a_team(db, admin):
    """Off by default, and 'off' has to mean something: a hand-made request must
    not attach itself to a queue on a form whose author turned sharing off."""
    requester = await make_user(db, name="Requester")
    team = await teams_service.create_team(db, TeamCreate(name=f"T{uuid.uuid4().hex[:6]}"))
    await teams_service.add_team_member(db, team.id, requester.id)
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)  # picker OFF

    with pytest.raises(ConflictError):
        await _file(db, form, requester, team_id=team.id)


# --- what must not leak -------------------------------------------------------


async def test_internal_comments_are_absent_from_the_thread_and_the_count(db, admin):
    """The one that leaks quietly. Hiding an internal comment from the LIST while
    counting it still tells the requester that internal discussion exists and how
    much of it there is, so both are asserted."""
    requester = await make_user(db, name="Requester")
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)
    filed = await _file(db, form, requester)

    await comments_service.create_comment(
        db,
        filed.id,
        CommentCreate(body="Visible reply", visibility=CommentVisibility.PUBLIC),
        admin,
        entity_type=CommentParentType.ITEM.value,
    )
    await comments_service.create_comment(
        db,
        filed.id,
        CommentCreate(body="Do not show this", visibility=CommentVisibility.INTERNAL),
        admin,
        entity_type=CommentParentType.ITEM.value,
    )

    detail = await requests_service.get_request(db, requester, filed.key)
    bodies = [c.body for c in detail.comments]
    assert bodies == ["Visible reply"]
    assert detail.comment_count == 1, "the count described the internal comment too"


async def test_an_internal_comment_does_not_light_the_reply_marker(db, admin):
    """`awaiting_requester` is a signal that someone answered YOU. An internal
    note lighting it would announce a conversation the requester cannot read."""
    requester = await make_user(db, name="Requester")
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)
    filed = await _file(db, form, requester)

    await comments_service.create_comment(
        db,
        filed.id,
        CommentCreate(body="internal only", visibility=CommentVisibility.INTERNAL),
        admin,
        entity_type=CommentParentType.ITEM.value,
    )
    [row] = [r for r in await requests_service.list_my_requests(db, requester) if r.key == filed.key]
    assert row.awaiting_requester is False
    assert row.comment_count == 0


async def test_the_reply_marker_tracks_who_spoke_last(db, admin):
    requester = await make_user(db, name="Requester")
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)
    filed = await _file(db, form, requester)

    def row():
        return requests_service.list_my_requests(db, requester)

    assert [r for r in await row() if r.key == filed.key][0].awaiting_requester is False

    await comments_service.create_comment(
        db,
        filed.id,
        CommentCreate(body="Have you tried restarting it?", visibility=CommentVisibility.PUBLIC),
        admin,
        entity_type=CommentParentType.ITEM.value,
    )
    assert [r for r in await row() if r.key == filed.key][0].awaiting_requester is True

    # The requester answers — the ball is no longer in their court.
    await requests_service.add_request_comment(db, requester, filed.key, "Yes, twice.")
    assert [r for r in await row() if r.key == filed.key][0].awaiting_requester is False


async def test_the_requesters_own_emailed_reply_does_not_light_the_marker(db, admin):
    """RADD-981: a mailed reply from someone with no account is authored by SYSTEM,
    which is not the reporter, so it must not read as "somebody answered you" (the SLA
    first-response timer skips it too). It is still COUNTED: a real public message."""
    from radd.modules.automations.types import SYSTEM_ACTOR_ID
    from radd.modules.auth import service as auth_service
    from radd.modules.comments.types import CommentOrigin

    requester = await make_user(db, name="Requester")
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)
    filed = await _file(db, form, requester)
    system = await auth_service.get_user(db, SYSTEM_ACTOR_ID)

    await comments_service.create_comment(
        db,
        filed.id,
        CommentCreate(body="Email reply from Cass:\n\nStill broken.",
                      visibility=CommentVisibility.PUBLIC),
        system,
        entity_type=CommentParentType.ITEM.value,
        # What intake stamps on mail no account stands behind (RADD-1318): the
        # marker reads the ORIGIN now, not "the author is SYSTEM".
        origin=CommentOrigin.INBOUND_MAIL,
    )
    [row] = [r for r in await requests_service.list_my_requests(db, requester) if r.key == filed.key]
    assert row.awaiting_requester is False
    assert row.comment_count == 1


async def test_a_requester_reply_is_public_and_authored_by_them(db, admin):
    """A requester holds `comment.write` nowhere; the relationship is the grant.
    The reply must land as THEIRS and as PUBLIC."""
    requester = await make_user(db, name="Requester")
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)
    filed = await _file(db, form, requester)

    reply = await requests_service.add_request_comment(db, requester, filed.key, "Any news?")
    assert reply.author_is_me is True
    assert reply.author == requester.name

    detail = await requests_service.get_request(db, requester, filed.key)
    assert [c.body for c in detail.comments] == ["Any news?"]
    assert detail.comment_count == 1


async def test_a_stranger_cannot_reply(db, admin):
    requester, stranger = (
        await make_user(db, name="Requester"),
        await make_user(db, name="Stranger"),
    )
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)
    filed = await _file(db, form, requester)

    with pytest.raises(NotFoundError):
        await requests_service.add_request_comment(db, stranger, filed.key, "let me in")


async def test_the_detail_view_carries_no_issue_internals(db, admin):
    """Opening a request is not reading the issue. Asserted as an EXACT field set
    so a future addition has to be a decision rather than an accident."""
    requester = await make_user(db, name="Requester")
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)
    filed = await _file(db, form, requester)

    detail = await requests_service.get_request(db, requester, filed.key)
    assert set(type(detail).model_fields) == {
        # the row (RADD-797)
        "key", "title", "state", "state_category", "project",
        "assignee", "release", "team", "team_id",
        "comment_count", "awaiting_requester", "created_at", "updated_at",
        # what opening it adds
        "description", "comments",
        "email_signature",  # reversible annotation over already-visible description text
    }


async def test_unattributed_import_comment_is_counted_but_not_an_agent_answer(db, admin):
    requester = await make_user(db, name="Requester")
    project = await make_project(db, "RV")
    form = await _shared_form(db, admin, project, requester)
    filed = await _file(db, form, requester)
    await comments_service.create_comment(db, filed.id,
        CommentCreate(body='Unknown historical author', author_id=None), admin)
    row = next(r for r in await requests_service.list_my_requests(db, requester) if r.key == filed.key)
    assert row.comment_count == 1
    assert row.awaiting_requester is False
