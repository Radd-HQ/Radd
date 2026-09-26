"""Board column presence on the view (RADD-1175).

Two facts worth pinning: both settings round-trip through create/update with
the same omitted-vs-null idiom as `column_order` (so a PATCH that says nothing
about them changes nothing, and an explicit null clears the hidden set), and
they are edit-gated like every other view field — a viewer who can see the
board cannot reshape it for everyone.

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest

from radd.exceptions import ForbiddenError
from radd.modules.auth.types import InstanceRole
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.views import service as views_service
from radd.modules.views.schemas import ViewCreate, ViewUpdate
from radd.modules.views.types import ShareLevel, ViewType

from _factories import make_user


async def _board(db, actor, **kwargs):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"BC{uuid.uuid4().hex[:4].upper()}", name="P")
    )
    return await views_service.create_view(
        db,
        ViewCreate(project_id=project.id, name="Board", view_type=ViewType.BOARD, **kwargs),
        actor=actor,
    )


async def test_presence_round_trips_with_the_bucket_order_idiom(db):
    actor = await make_user(db, role=InstanceRole.ADMIN, name="Board Tester")
    created = await _board(db, actor)
    assert created.collapse_empty_columns is False and created.hidden_columns is None

    on = await views_service.update_view(
        db, created.id, ViewUpdate(collapse_empty_columns=True, hidden_columns=["a", " ", "b"]), actor
    )
    assert on.collapse_empty_columns is True
    assert on.hidden_columns == ["a", "b"]  # blanks dropped, like column_order

    # Omitted = unchanged: a rename touches neither.
    renamed = await views_service.update_view(db, created.id, ViewUpdate(name="B2"), actor)
    assert renamed.collapse_empty_columns is True and renamed.hidden_columns == ["a", "b"]

    # Explicit null = nothing hidden; the switch stays where it was.
    cleared = await views_service.update_view(db, created.id, ViewUpdate(hidden_columns=None), actor)
    assert cleared.hidden_columns is None and cleared.collapse_empty_columns is True

    born_with = await _board(db, actor, collapse_empty_columns=True, hidden_columns=["x"])
    assert born_with.collapse_empty_columns is True and born_with.hidden_columns == ["x"]


async def test_presence_is_edit_gated(db):
    """A VIEWER — someone the view is shared with read-only — can see the board
    but cannot reshape it for everyone. (A stranger gets a 404: the view is
    invisible to them, which is the stronger refusal.)"""
    owner = await make_user(db, role=InstanceRole.ADMIN, name="Board Tester")
    created = await _board(db, owner, global_access=ShareLevel.VIEWER)
    bystander = await make_user(db, name="Board Tester")
    assert (await views_service.get_view_read(db, created.id, bystander)).can_edit is False
    with pytest.raises(ForbiddenError):
        await views_service.update_view(
            db, created.id, ViewUpdate(collapse_empty_columns=True), bystander
        )
