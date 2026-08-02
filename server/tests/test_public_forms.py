"""Public form path + mail contacts (spec 62), driven through the real services
against live Postgres in a rolled-back transaction (nothing persists):

- the public token lifecycle (minted on first enable, kept on disable),
- 404 unknown token / 409 disabled-or-not-public,
- render payload carries inline field definitions,
- submit: email → registered reporter, or reporter NULL + mail_contacts row + ack,
- authenticated submits still credit the acting user as reporter,
- upsert_contact keeps one contact per item (address never overwritten).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd import smtp as smtp_util
from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldType
from radd.modules.forms import public, service as forms_service
from radd.modules.forms.schemas import (
    FormCreate,
    FormField,
    FormSubmit,
    FormUpdate,
    PublicFormSubmit,
)
from radd.modules.items import service as items_service
from radd.modules.mailintake import service as mail_service
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"pf-{uuid.uuid4().hex[:8]}@example.com",
        name="Public Forms Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db) -> Project:
    return await projects_service.create_project(
        db, ProjectCreate(key="PUB62", name="Public intake")
    )


async def _public_form(db, admin, project, **create_kwargs) -> tuple[uuid.UUID, str]:
    """A publicly-enabled form; returns (form_id, token)."""
    form = await forms_service.create_form(
        db, FormCreate(project_id=project.id, name="Support request", **create_kwargs), admin
    )
    enabled = await forms_service.update_form(db, form.id, FormUpdate(allow_public=True), admin)
    assert enabled.public_token is not None
    return form.id, enabled.public_token


# --- token lifecycle + gating ---


async def test_public_token_minted_once_and_kept_on_disable(db, admin, project):
    form = await forms_service.create_form(
        db, FormCreate(project_id=project.id, name="Support"), admin
    )
    assert form.allow_public is False and form.public_token is None

    enabled = await forms_service.update_form(db, form.id, FormUpdate(allow_public=True), admin)
    token = enabled.public_token
    assert enabled.allow_public and token

    # Disable: the link stops working but the token survives …
    disabled = await forms_service.update_form(db, form.id, FormUpdate(allow_public=False), admin)
    assert disabled.public_token == token
    with pytest.raises(ConflictError):
        await public.render_public_form(db, token)

    # … so re-enabling restores the SAME link.
    reenabled = await forms_service.update_form(db, form.id, FormUpdate(allow_public=True), admin)
    assert reenabled.public_token == token
    rendered = await public.render_public_form(db, token)
    assert rendered.name == "Support"


async def test_unknown_token_is_404_and_disabled_form_is_409(db, admin, project):
    with pytest.raises(NotFoundError):
        await public.render_public_form(db, "not-a-real-token")
    form_id, token = await _public_form(db, admin, project)
    await forms_service.update_form(db, form_id, FormUpdate(enabled=False), admin)
    with pytest.raises(ConflictError):  # public but the form itself is off
        await public.submit_public_form(
            db, token, PublicFormSubmit(title="x", email="a@b.co")
        )


# --- render payload ---


async def test_render_inlines_field_definitions_with_overrides(db, admin, project):
    await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_id=project.id,
            key="severity",
            name="Severity",
            type=FieldType.SELECT,
            options=["low", "high"],
        ),
        actor_id=admin.id,
    )
    _, token = await _public_form(
        db,
        admin,
        project,
        fields=[FormField(field_key="severity", label_override="How bad?", required=True)],
    )
    rendered = await public.render_public_form(db, token)
    assert [
        (f.field_key, f.label, f.required, f.type, f.options) for f in rendered.fields
    ] == [("severity", "How bad?", True, FieldType.SELECT.value, ["low", "high"])]


# --- submit: reporter resolution + contact capture ---


async def test_submit_with_unknown_email_creates_contact_and_null_reporter(db, admin, project):
    _, token = await _public_form(db, admin, project)
    result = await public.submit_public_form(
        db,
        token,
        PublicFormSubmit(title="Printer on fire", email="Jane@External.com", name="Jane"),
    )
    assert result.key.startswith(project.key)
    item = await items_service.find_item_by_key(db, result.key)
    assert item is not None and item.reporter_id is None
    contact = await mail_service.contact_for_item(db, item.id)
    assert contact is not None
    assert contact.email == "jane@external.com" and contact.name == "Jane"


async def test_submit_with_registered_email_sets_reporter_and_no_contact(db, admin, project):
    _, token = await _public_form(db, admin, project)
    result = await public.submit_public_form(
        db, token, PublicFormSubmit(title="More RAM please", email=admin.email)
    )
    item = await items_service.find_item_by_key(db, result.key)
    assert item is not None and item.reporter_id == admin.id
    assert await mail_service.contact_for_item(db, item.id) is None


async def test_authenticated_submit_still_credits_the_actor_as_reporter(db, admin, project):
    # Regression guard for the reporter model_fields_set change in items.create_item.
    form = await forms_service.create_form(
        db, FormCreate(project_id=project.id, name="Internal"), admin
    )
    created = await forms_service.submit_form(
        db, form.id, FormSubmit(title="raised while logged in"), admin
    )
    item = await items_service.find_item_by_key(db, created.key)
    assert item is not None and item.reporter_id == admin.id


async def test_submit_sends_ack_through_the_smtp_helper(db, admin, project, monkeypatch):
    sent: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")  # dev default is "" = off
    monkeypatch.setattr(smtp_util, "send_message", lambda *a, **k: sent.append((a, k)))
    _, token = await _public_form(db, admin, project)

    result = await public.submit_public_form(
        db, token, PublicFormSubmit(title="No sound", email="ext@example.com", name="Ext")
    )
    assert len(sent) == 1
    (to_address, subject, body), kwargs = sent[0][0], sent[0][1]
    assert to_address == "ext@example.com"
    assert subject == f"[{result.key}] No sound"
    assert result.key in body
    assert kwargs["to_name"] == "Ext"

    # A registered submitter gets watcher notifications instead — no ack.
    await public.submit_public_form(
        db, token, PublicFormSubmit(title="Again", email=admin.email)
    )
    assert len(sent) == 1


# --- contact upsert semantics (one contact per item) ---


async def test_upsert_contact_never_overwrites_the_address(db, admin, project):
    _, token = await _public_form(db, admin, project)
    result = await public.submit_public_form(
        db, token, PublicFormSubmit(title="Flickering", email="first@example.com")
    )
    item = await items_service.find_item_by_key(db, result.key)
    assert item is not None

    updated = await mail_service.upsert_contact(
        db, item.id, email="second@example.com", name="Second", message_id="<m2@x>"
    )
    assert updated.email == "first@example.com"  # address is sticky
    assert updated.last_message_id == "<m2@x>"  # threading pointer advances
    assert updated.name == "Second"  # blank name backfilled


# --- the description area (a builtin, not a registry field) ---


async def test_submitted_description_lands_on_the_item(db, admin, project):
    _, token = await _public_form(db, admin, project)  # description_enabled defaults True
    result = await public.submit_public_form(
        db,
        token,
        PublicFormSubmit(
            title="Broken render", description="Steps: open scene, hit render.", email="a@b.co"
        ),
    )
    item = await items_service.find_item_by_key(db, result.key)
    assert item is not None and item.description == "Steps: open scene, hit render."


async def test_required_description_rejects_blank_and_disabled_area_ignores_it(db, admin, project):
    from radd.modules.forms.validation import FormValidationError

    required_form = await forms_service.create_form(
        db,
        FormCreate(project_id=project.id, name="Strict", description_required=True),
        admin,
    )
    with pytest.raises(FormValidationError):
        await forms_service.submit_form(
            db, required_form.id, FormSubmit(title="No details", description="   "), admin
        )

    # Area disabled: a submitted description is ignored, required is moot.
    off_form = await forms_service.create_form(
        db,
        FormCreate(
            project_id=project.id,
            name="No description",
            description_enabled=False,
            description_required=True,
        ),
        admin,
    )
    created = await forms_service.submit_form(
        db, off_form.id, FormSubmit(title="Quick one", description="ignore me"), admin
    )
    assert created.description == ""


async def test_render_carries_the_description_prompt(db, admin, project):
    _, token = await _public_form(
        db, admin, project, description_prompt="What happened?", description_required=True
    )
    rendered = await public.render_public_form(db, token)
    assert rendered.description_enabled is True
    assert rendered.description_prompt == "What happened?"
    assert rendered.description_required is True