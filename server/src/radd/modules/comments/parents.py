"""What a comment can hang off (RADD-717).

A module registers a `CommentParent` at plugin init (same shape as
`attachments/parents.py`), so `comments` never learns that `pages` exists.
A binding answers:
  - `project_of`: the owning project, or None for a global parent such as a
    wiki page. The permission checks then run at global scope, which is how
    page atoms are granted.
  - `require_read`: a comment is never more visible than its parent.
  - `require_write`: may this actor comment on it.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.items.enums import ItemEvent
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
    #: Event emitted when a parent of this kind is destroyed. It replaces the FK's
    #: ON DELETE CASCADE: `gc.cascades` derives one sweep per binding from it, so
    #: a plugin that registers a parent gets cleanup with no edit here.
    deleted_event: str


_BINDINGS: dict[str, CommentParent] = {}


def register_parent(binding: CommentParent) -> None:
    """Register a parent; its cleanup follows (gc.cascades derives from this registry)."""
    _BINDINGS[binding.entity_type] = binding


def bindings() -> list[CommentParent]:
    """Every registered parent — the GC builds its event map from this."""
    return list(_BINDINGS.values())


def binding_for(entity_type: str) -> CommentParent:
    binding = _BINDINGS.get(entity_type)
    if binding is None:
        raise NotFoundError(CommentEntity.COMMENT, f"parent type {entity_type!r}")
    return binding


# --- the item binding (comments' own) -----------------------------------------


async def _item_project(session: AsyncSession, item_id: uuid.UUID) -> Project:
    item = await items_service.require_item(session, item_id)
    return await projects_service.get_project(session, item.project_id)


async def _item_read(session, user: User, entity_id: uuid.UUID, project):
    # RADD-823: through THE item seam, so comments inherit per-item read rules.
    _item, _project, permissions = await items_service.require_readable_item(
        session, entity_id, user
    )
    return permissions


async def _item_write(session, user: User, entity_id: uuid.UUID, project):
    permissions = await authz.require(session, user, Permission.COMMENT_WRITE, project=project)
    # RADD-844: a qualified comment.write names a relation to the PARENT item
    # (`@participant`/`@own`: items shared with them / they reported); @any skips this.
    if authz.RELATION_ANY not in authz.relations_held(permissions, Permission.COMMENT_WRITE):
        item = await items_service.require_item(session, entity_id)
        await items_service.ensure_item_relation(
            session, user, item, permissions, Permission.COMMENT_WRITE
        )
    return permissions


register_parent(
    CommentParent(
        entity_type=CommentParentType.ITEM.value,
        deleted_event=str(ItemEvent.DELETED),
        project_of=_item_project,
        require_read=_item_read,
        require_write=_item_write,
        # Spec 50's rule, unchanged: editing another's comment is project.manage.
        manage_permission=Permission.PROJECT_MANAGE,
    )
)
