"""What a comment can hang off (RADD-717).

Comments were not merely item-KEYED, they were item-SHAPED: the owning project
came from `items.require_item`, visibility was decided against that project, and
every permission check was project-scoped. A page has no project, so making a
page own a comment is this seam, not a column rename.

Same shape as `attachments/parents.py` (spec 102), deliberately — that binding
registry already solved "several kinds of thing own the same child", and a
second registry with different vocabulary would be one more thing to learn. A
module registers its own binding at plugin init, so `comments` never learns that
`pages` exists (dev rule 1).

A binding answers three questions:

  - **Where does this live?** `project_of` returns the owning project, or None
    for a globally-scoped parent like a wiki page. None is not an error state:
    it means the permission checks run at global scope, which is exactly how
    page atoms are granted.
  - **May this actor read it?** `require_read` — a comment is never more visible
    than the thing it is attached to.
  - **May this actor comment on it?** `require_write`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .types import CommentEntity, CommentParentType

#: (session, entity_id) -> the owning project, or None when the parent is global.
ProjectOf = Callable[[AsyncSession, uuid.UUID], Awaitable[Project | None]]
#: (session, user, entity_id, project) -> the actor's effective permissions.
Guard = Callable[..., Awaitable[frozenset[Permission]]]


@dataclass(frozen=True)
class CommentParent:
    entity_type: str
    project_of: ProjectOf
    require_read: Guard
    require_write: Guard
    #: Editing or deleting SOMEONE ELSE'S comment on this parent.
    manage_permission: Permission
    #: The event type emitted when a parent of this kind is destroyed.
    #:
    #: This is what replaces the foreign key's ON DELETE CASCADE. A polymorphic
    #: column cannot carry an FK, so cleanup has to be driven by something —
    #: and putting it on the BINDING rather than in a table inside the GC means
    #: a plugin that registers a parent gets cleanup automatically instead of
    #: needing an edit to a module it does not own. (attachments/gc.py keeps
    #: that map hardcoded, which is exactly the seam a plugin cannot reach.)
    deleted_event: str


_BINDINGS: dict[str, CommentParent] = {}


def register_parent(binding: CommentParent) -> None:
    _BINDINGS[binding.entity_type] = binding


def bindings() -> list[CommentParent]:
    """Every registered parent — the GC builds its event map from this."""
    return list(_BINDINGS.values())


def binding_for(entity_type: str) -> CommentParent:
    binding = _BINDINGS.get(entity_type)
    if binding is None:
        raise NotFoundError(CommentEntity.COMMENT, f"parent type {entity_type!r}")
    return binding


def registered_types() -> list[str]:
    return sorted(_BINDINGS)


# --- the item binding (comments' own) -----------------------------------------


async def _item_project(session: AsyncSession, item_id: uuid.UUID) -> Project:
    item = await items_service.require_item(session, item_id)
    return await projects_service.get_project(session, item.project_id)


async def _item_read(session, user: User, entity_id: uuid.UUID, project):
    return await authz.require(session, user, Permission.ITEM_READ, project=project)


async def _item_write(session, user: User, entity_id: uuid.UUID, project):
    return await authz.require(session, user, Permission.COMMENT_WRITE, project=project)


register_parent(
    CommentParent(
        entity_type=CommentParentType.ITEM.value,
        deleted_event="item.deleted",
        project_of=_item_project,
        require_read=_item_read,
        require_write=_item_write,
        # Spec 50's rule, unchanged: editing another's comment is project.manage.
        manage_permission=Permission.PROJECT_MANAGE,
    )
)
