"""Requester portal (spec 73): eligibility listing (public OR shared, grouped
by project), portal submits as the SYSTEM actor with the sharee as reporter
(no item.create needed — the share is the grant), and share-subject validation
on PUT /forms/{id}/sharing (full-replace).

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.forms import portal, requests as requests_service, service as forms_service
from radd.modules.forms.schemas import (
    FormCreate,
    FormShareEntry,
    FormSharingUpdate,
    FormSubmit,
    FormUpdate,
)
from radd.modules.items import service as items_service
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"ptl-{uuid.uuid4().hex[:8]}@example.com",
        name="Portal Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _member(db, name: str) -> User:
    """A plain active user: the global member floor grants item.read but NOT item.create."""
    user = User(
        email=f"ptl-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db):
    return await projects_service.create_project(
        db,
        ProjectCreate(key=f"PT{uuid.uuid4().hex[:4].upper()}", name="Portal P"),
    )


async def _team(db):
    return await teams_service.create_team(
        db, TeamCreate(name=f"Desk {uuid.uuid4().hex[:6]}")
    )


async def _form(db, admin, project, name: str, **kwargs):
    return await forms_service.create_form(
        db, FormCreate(project_id=project.id, name=name, **kwargs), admin
    )


def _form_ids(groups) -> set[uuid.UUID]:
    return {card.id for group in groups for card in group.forms}


# --- (a) the directory: public OR shared, disabled excluded ---


async def test_portal_listing_eligibility(db, admin):
    project = await _project(db)
    member = await _member(db, "Member")
    teammate = await _member(db, "Teammate")
    team = await _team(db)
    await teams_service.add_team_member(db, team.id, teammate.id)

    public_form = await _form(db, admin, project, "Public intake")
    await forms_service.update_form(db, public_form.id, FormUpdate(allow_public=True), admin)
    team_shared = await _form(db, admin, project, "Team desk")
    await forms_service.update_sharing(
        db, team_shared.id, FormSharingUpdate(shares=[FormShareEntry(team_id=team.id)]), admin
    )
    disabled = await _form(db, admin, project, "Old intake")
    await forms_service.update_form(
        db, disabled.id, FormUpdate(allow_public=True, enabled=False), admin
    )
    unshared = await _form(db, admin, project, "Managers only")

    # Any member sees the public form; the team share is invisible outside the
    # team; disabled and unshared forms never list.
    member_ids = _form_ids(await portal.list_portal_forms(db, member))
    assert public_form.id in member_ids
    assert team_shared.id not in member_ids
    assert disabled.id not in member_ids
    assert unshared.id not in member_ids

    # A team member sees the team-shared form too, grouped under the project.
    groups = await portal.list_portal_forms(db, teammate)
    assert {public_form.id, team_shared.id} <= _form_ids(groups)
    group = next(g for g in groups if g.project.id == project.id)
    assert (group.project.key, group.project.name) == (project.key, project.name)


# --- (b) portal submit: the share is the grant; ineligible → 404 ---


async def test_portal_submit_as_sharee_without_item_create(db, admin):
    project = await _project(db)
    sharee = await _member(db, "Sharee")
    bystander = await _member(db, "Bystander")
    form = await _form(db, admin, project, "Access request")
    await forms_service.update_sharing(
        db, form.id, FormSharingUpdate(shares=[FormShareEntry(user_id=sharee.id)]), admin
    )

    # The sharee holds only the member floor — no item.create anywhere.
    perms = await authz.require(db, sharee, Permission.ITEM_READ, project=project)
    assert Permission.ITEM_CREATE not in perms

    result = await portal.submit_portal_form(
        db, form.id, FormSubmit(title="Need a license", description="For rendering."), sharee
    )
    assert result.key.startswith(project.key)
    item = await items_service.find_item_by_key(db, result.key)
    assert item is not None
    assert item.reporter_id == sharee.id  # the visitor, not the SYSTEM actor
    assert item.description == "For rendering."

    # Ineligible actors get a plain 404 — render and submit alike.
    with pytest.raises(NotFoundError):
        await portal.render_portal_form(db, form.id, bystander)
    with pytest.raises(NotFoundError):
        await portal.submit_portal_form(db, form.id, FormSubmit(title="nope"), bystander)

    # Eligible render carries the public trimming plus the project ref.
    rendered = await portal.render_portal_form(db, form.id, sharee)
    assert rendered.id == form.id and rendered.project.key == project.key
    assert rendered.description_enabled is True


# --- (c) sharing PUT: subject validation + full-replace semantics ---


async def test_sharing_put_validation_and_full_replace(db, admin):
    project = await _project(db)
    colleague = await _member(db, "Colleague")
    # Spec 86: any ACTIVE user + any team is a valid subject (the global member
    # floor). Only an INACTIVE user or duplicate entries are rejected.
    inactive = User(
        email=f"ptl-out-{uuid.uuid4().hex[:8]}@example.com",
        name="Gone",
        instance_role=InstanceRole.MEMBER.value,
        active=False,
    )
    db.add(inactive)
    await db.flush()
    form = await _form(db, admin, project, "Shared intake")

    # An inactive user / duplicate entries → 409.
    with pytest.raises(ConflictError):
        await forms_service.update_sharing(
            db, form.id, FormSharingUpdate(shares=[FormShareEntry(user_id=inactive.id)]), admin
        )
    with pytest.raises(ConflictError):
        await forms_service.update_sharing(
            db,
            form.id,
            FormSharingUpdate(
                shares=[
                    FormShareEntry(user_id=colleague.id),
                    FormShareEntry(user_id=colleague.id),
                ]
            ),
            admin,
        )

    # Full replace: the PUT is the whole state — the user row gives way to the team row.
    team = await _team(db)
    read = await forms_service.update_sharing(
        db, form.id, FormSharingUpdate(shares=[FormShareEntry(user_id=colleague.id)]), admin
    )
    assert [(s.user_id, s.team_id) for s in read.shares] == [(colleague.id, None)]
    read = await forms_service.update_sharing(
        db, form.id, FormSharingUpdate(shares=[FormShareEntry(team_id=team.id)]), admin
    )
    assert [(s.user_id, s.team_id) for s in read.shares] == [(None, team.id)]


async def test_my_requests_is_scoped_by_reporter_not_by_permission(db, admin):
    """RADD-785: your own request is yours to see, with no `item.read` involved.

    That is the whole point. The configuration that makes a clean requester —
    a Baseline carrying no read at all — is exactly the one that would otherwise
    leave them unable to see the ticket they just filed.
    """
    project = await _project(db)
    sharee = await _member(db, "Requester")
    other = await _member(db, "Someone else")
    form = await _form(db, admin, project, "Access request")
    await forms_service.update_sharing(
        db, form.id, FormSharingUpdate(shares=[FormShareEntry(user_id=sharee.id)]), admin
    )

    await portal.submit_portal_form(db, form.id, FormSubmit(title="A new laptop"), sharee)

    mine = await requests_service.list_my_requests(db, sharee)
    assert [r.title for r in mine] == ["A new laptop"]
    assert mine[0].key.startswith(project.key)
    assert mine[0].project.key == project.key
    assert mine[0].state  # the workflow state, for "where has it got to"

    # Someone else's portal shows nothing of it.
    assert await requests_service.list_my_requests(db, other) == []


async def test_my_requests_exposes_no_issue_contents(db, admin):
    """The trimming is the security boundary, so it is asserted rather than assumed.

    A requester is scoped by their RELATIONSHIP to the row, not by `item.read`,
    so this read model must never grow into a back door.

    RADD-797 widened the row deliberately, and this list is the record of what
    was allowed in and why: a status a requester needs, never issue CONTENT.
    `assignee` is a name from the member-floor directory (RADD-769), `release` is
    a version string, and the two numbers are derived from PUBLIC comments only.
    Still absent, and the point of asserting an EXACT set: description, labels,
    custom fields, worklogs, history, and anything internal. The description and
    the public thread moved to `PortalRequestDetail`, behind the same admission
    rule but as an explicit act of opening one request.
    """
    project = await _project(db)
    sharee = await _member(db, "Requester")
    form = await _form(db, admin, project, "Access request")
    await forms_service.update_sharing(
        db, form.id, FormSharingUpdate(shares=[FormShareEntry(user_id=sharee.id)]), admin
    )
    await portal.submit_portal_form(
        db, form.id, FormSubmit(title="Secret-ish", description="internal details"), sharee
    )

    fields = set(type((await requests_service.list_my_requests(db, sharee))[0]).model_fields)
    assert fields == {
        "key", "title", "state", "state_category", "project",
        "assignee", "release", "team", "team_id", "comment_count",
        "awaiting_requester", "created_at", "updated_at",
    }
