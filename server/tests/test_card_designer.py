"""Card designer (spec 109): the views.card_layout round-trip + semantic
validation, and the card-layout preset library's CRUD + RBAC atoms.

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist.
"""

import uuid

import pytest
from pydantic import ValidationError

from radd.config import settings as config
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole, Permission, expand_permissions
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.views import service as views_service
from radd.modules.views.schemas import (
    CardLayout,
    CardLayoutCell,
    CardPresetCreate,
    CardPresetUpdate,
    ViewCreate,
    ViewUpdate,
)
from radd.modules.views.types import ViewType
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def actor(db) -> User:
    user = User(
        email=f"cd-{uuid.uuid4().hex[:8]}@example.com",
        name="Card Designer Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


def _layout(*cells: dict, max_labels: int = 3) -> CardLayout:
    return CardLayout(
        cells=[CardLayoutCell(**cell) for cell in cells], max_labels=max_labels
    )


DEFAULT_ISH = (
    {"attr": "priority", "row": 0, "col": 7, "span": 1, "align": "end"},
    {"attr": "title", "row": 1, "col": 0, "span": 8},
    {"attr": "labels", "row": 2, "col": 0, "span": 8},
    {"attr": "assignee", "row": 3, "col": 7, "span": 1, "align": "end"},
)


async def _board(db, actor, **kwargs):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"CD{uuid.uuid4().hex[:4].upper()}", name="P")
    )
    return await views_service.create_view(
        db,
        ViewCreate(project_id=project.id, name="Board", view_type=ViewType.BOARD, **kwargs),
        actor=actor,
    )


# --- views.card_layout ---


async def test_card_layout_round_trip_and_clear(db, actor):
    created = await _board(db, actor, card_layout=_layout(*DEFAULT_ISH, max_labels=2))
    assert created.card_layout is not None
    assert created.card_layout.max_labels == 2
    assert [c.attr for c in created.card_layout.cells] == [
        "priority",
        "title",
        "labels",
        "assignee",
    ]

    # Unrelated PATCH leaves the layout alone (model_fields_set idiom)…
    renamed = await views_service.update_view(db, created.id, ViewUpdate(name="B2"), actor)
    assert renamed.card_layout == created.card_layout
    # …a set PATCH replaces it…
    two_cell = _layout(
        {"attr": "title", "row": 0, "col": 0, "span": 6},
        {"attr": "cf.studio", "row": 0, "col": 6, "span": 2, "align": "end"},
    )
    updated = await views_service.update_view(
        db, created.id, ViewUpdate(card_layout=two_cell), actor
    )
    assert updated.card_layout is not None
    assert {c.attr for c in updated.card_layout.cells} == {"title", "cf.studio"}
    # …and an explicit null = back to the type's default card.
    cleared = await views_service.update_view(
        db, created.id, ViewUpdate(card_layout=None), actor
    )
    assert cleared.card_layout is None


async def test_card_layout_semantic_validation(db, actor):
    # Duplicate attr -> 409.
    with pytest.raises(ConflictError):
        await _board(
            db,
            actor,
            card_layout=_layout(
                {"attr": "title", "row": 0, "col": 0, "span": 4},
                {"attr": "labels", "row": 1, "col": 0, "span": 4},
                {"attr": "labels", "row": 1, "col": 4, "span": 4},
            ),
        )
    # No title cell -> 409 (it is the one mandatory cell).
    with pytest.raises(ConflictError):
        await _board(db, actor, card_layout=_layout({"attr": "labels", "row": 0, "col": 0, "span": 8}))
    # col + span past the grid edge -> 409.
    with pytest.raises(ConflictError):
        await _board(
            db,
            actor,
            card_layout=_layout({"attr": "title", "row": 0, "col": 4, "span": 8}),
        )
    # Same-row range overlap -> 409.
    with pytest.raises(ConflictError):
        await _board(
            db,
            actor,
            card_layout=_layout(
                {"attr": "title", "row": 0, "col": 0, "span": 5},
                {"attr": "assignee", "row": 0, "col": 3, "span": 1},
            ),
        )


def test_card_layout_shape_validation():
    # Shape errors are pydantic's (422 at the boundary), not the service's.
    with pytest.raises(ValidationError):
        CardLayoutCell(attr="title", row=0, col=0, span=0)  # span >= 1
    with pytest.raises(ValidationError):
        CardLayoutCell(attr="title", row=9, col=0, span=1)  # row < 8
    with pytest.raises(ValidationError):
        CardLayoutCell(attr="title", row=0, col=8, span=1)  # col < 8
    with pytest.raises(ValidationError):
        CardLayout(
            cells=[
                CardLayoutCell(attr=f"cf.f{i}", row=0, col=0, span=1) for i in range(25)
            ]
        )  # cell cap


# --- the preset library ---


async def test_card_presets_crud(db, actor):
    layout = _layout(*DEFAULT_ISH)
    created = await views_service.create_card_preset(
        db, CardPresetCreate(name="Compact", layout=layout), actor
    )
    assert created.name == "Compact"

    listed = await views_service.list_card_presets(db)
    assert any(p.id == created.id for p in listed)

    renamed = await views_service.update_card_preset(
        db, created.id, CardPresetUpdate(name="Compact v2"), actor
    )
    assert renamed.name == "Compact v2"
    # The stored layout is untouched by a name-only PATCH.
    assert renamed.layout["cells"][0]["attr"] == "priority"

    # A preset's layout passes the same validator — and empty is refused.
    with pytest.raises(ConflictError):
        await views_service.create_card_preset(
            db, CardPresetCreate(name="Empty", layout=CardLayout(cells=[])), actor
        )

    await views_service.delete_card_preset(db, created.id, actor)
    assert not any(p.id == created.id for p in await views_service.list_card_presets(db))


async def test_card_preset_rbac_atoms(db):
    # global.manage expands (transitively) to the cardpreset atoms — RADD-816
    # deleted the dead cardpreset.manage umbrella; the CRUD atoms are the truth.
    expanded = expand_permissions({Permission.GLOBAL_MANAGE})
    assert {
        Permission.CARD_PRESET_READ.value,
        Permission.CARD_PRESET_CREATE.value,
        Permission.CARD_PRESET_UPDATE.value,
        Permission.CARD_PRESET_DELETE.value,
    } <= expanded
    # …and a plain member (no grants) is refused at the write gate the router
    # checks, while the member floor still covers browsing (ITEM_READ).
    member = User(
        email=f"cd-m-{uuid.uuid4().hex[:8]}@example.com",
        name="Member",
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(member)
    await db.flush()
    await authz.require(db, member, Permission.ITEM_READ)  # no raise
    with pytest.raises(ForbiddenError):
        await authz.require(db, member, Permission.CARD_PRESET_CREATE)
