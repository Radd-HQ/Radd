"""Who may resolve a thread (RADD-1283): the rule, and one reader's reach under it.

A project states the rule — a default plus per-issue-type overrides — as rows in
`thread_resolution_rules`. Everything that asks "may this person resolve this
thread?" goes through `resolve_reach`: `set_resolved` enforces it, and every
comment read carries its answer as `can_resolve`, so the browser never restates
the rule (it used to, three times, before the rule could vary).

Pages have no project and no issue type, so a page thread always takes
`DEFAULT_THREAD_RESOLVERS` — with the page binding's own manage permission.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.events import service as events
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.items.models import WorkItem
from radd.modules.itemtypes import service as itemtypes

from .models import Comment, ThreadResolutionRule
from .parents import binding_for
from .schemas import ThreadResolutionOverride, ThreadResolutionPolicy
from .types import (
    DEFAULT_THREAD_RESOLVERS,
    CommentEntity,
    CommentEvent,
    CommentParentType,
    ResolveReach,
    ThreadResolvers,
)


# --- the rule ------------------------------------------------------------------


async def _rules(session: AsyncSession, project_id: uuid.UUID) -> list[ThreadResolutionRule]:
    return list((await session.scalars(
        select(ThreadResolutionRule).where(ThreadResolutionRule.project_id == project_id)
    )).all())


async def get_policy(session: AsyncSession, project_id: uuid.UUID) -> ThreadResolutionPolicy:
    rules = await _rules(session, project_id)
    default = next((r.resolvers for r in rules if r.issue_type_id is None), DEFAULT_THREAD_RESOLVERS)
    return ThreadResolutionPolicy(
        default=ThreadResolvers(default),
        overrides=[
            ThreadResolutionOverride(issue_type_id=r.issue_type_id, resolvers=ThreadResolvers(r.resolvers))
            for r in rules if r.issue_type_id is not None
        ],
    )


async def resolvers_for_item(session: AsyncSession, item: WorkItem) -> ThreadResolvers:
    """The item's type's rule, else the project's, else the default."""
    rows = (await session.execute(
        select(ThreadResolutionRule.issue_type_id, ThreadResolutionRule.resolvers).where(
            ThreadResolutionRule.project_id == item.project_id,
            (ThreadResolutionRule.issue_type_id == item.type_id)
            | ThreadResolutionRule.issue_type_id.is_(None),
        )
    )).all()
    by_scope = dict(rows)
    chosen = by_scope.get(item.type_id) if item.type_id else None
    return ThreadResolvers(chosen or by_scope.get(None) or DEFAULT_THREAD_RESOLVERS)


async def set_policy(
    session: AsyncSession, project_id: uuid.UUID, data: ThreadResolutionPolicy, actor: User
) -> ThreadResolutionPolicy:
    """Replace the project's rules. The default is stored only when it differs
    from `DEFAULT_THREAD_RESOLVERS`, so "no row" keeps meaning "never set"."""
    type_ids = [override.issue_type_id for override in data.overrides]
    if len(set(type_ids)) != len(type_ids):
        raise ConflictError(CommentEntity.RESOLUTION_POLICY, reason="An issue type has more than one rule")
    types = await itemtypes.types_by_ids(session, type_ids)
    for type_id in type_ids:
        issue_type = types.get(type_id)
        if issue_type is None or issue_type.project_id != project_id:
            raise NotFoundError("issue_type", type_id)

    before = await get_policy(session, project_id)
    await session.execute(delete(ThreadResolutionRule).where(ThreadResolutionRule.project_id == project_id))
    if data.default is not DEFAULT_THREAD_RESOLVERS:
        session.add(ThreadResolutionRule(project_id=project_id, issue_type_id=None, resolvers=data.default.value))
    for override in data.overrides:
        session.add(ThreadResolutionRule(
            project_id=project_id, issue_type_id=override.issue_type_id, resolvers=override.resolvers.value,
        ))
    await session.flush()

    changes = _diff(before, data, {**types, **await itemtypes.types_by_ids(
        session, [o.issue_type_id for o in before.overrides])})
    if changes:
        await events.emit(
            session,
            event_type=CommentEvent.RESOLUTION_POLICY_UPDATED,
            entity_type=CommentEntity.RESOLUTION_POLICY,
            entity_id=project_id,
            actor_id=actor.id,
            payload={"project_id": str(project_id)},
            subjects={"project": project_id},
            changes=changes,
        )
    return await get_policy(session, project_id)


def _diff(before: ThreadResolutionPolicy, after: ThreadResolutionPolicy, types: dict) -> list[dict]:
    """Old → new per scope, named for a person: "default", or the issue type's name."""
    def scopes(policy: ThreadResolutionPolicy) -> dict[str, str]:
        named = {"default": policy.default.value}
        for override in policy.overrides:
            issue_type = types.get(override.issue_type_id)
            named[f"type:{issue_type.name if issue_type else override.issue_type_id}"] = override.resolvers.value
        return named

    old, new = scopes(before), scopes(after)
    return [
        {"field": key, "from": old.get(key), "to": new.get(key)}
        for key in sorted(old.keys() | new.keys())
        if old.get(key) != new.get(key)
    ]


# --- one reader's reach ----------------------------------------------------------


async def resolve_reach(
    session: AsyncSession, actor: User, entity_type: str, entity_id: uuid.UUID
) -> ResolveReach:
    """What `actor` may resolve on this parent: every thread, their own, or none.

    Managers hold the parent's manage permission (project.manage on an issue,
    page.manage on a page). "May write" is the binding's own comment gate, so a
    relation-qualified `comment.write` is honoured exactly as it is for posting.
    """
    binding = binding_for(entity_type)
    project = await binding.project_of(session, entity_id)
    try:
        permissions = await binding.require_write(session, actor, entity_id, project)
        writer = True
    except (ForbiddenError, NotFoundError):
        permissions = await authz.effective_permissions(session, actor, project=project)
        writer = False
    manager = binding.manage_permission in permissions

    resolvers = DEFAULT_THREAD_RESOLVERS
    assignee = False
    if entity_type == CommentParentType.ITEM.value:
        item = await session.get(WorkItem, entity_id)
        if item is not None:
            resolvers = await resolvers_for_item(session, item)
            assignee = item.assignee_id is not None and item.assignee_id == actor.id

    if resolvers is ThreadResolvers.MANAGERS:
        return ResolveReach.ANY if manager else ResolveReach.NONE
    if manager:
        return ResolveReach.ANY
    if not writer:
        return ResolveReach.NONE
    if resolvers is ThreadResolvers.ANYONE or (resolvers is ThreadResolvers.ASSIGNEE and assignee):
        return ResolveReach.ANY
    return ResolveReach.OWN


def reach_covers(reach: ResolveReach, comment: Comment, actor: User) -> bool:
    """Whether `reach` extends to this thread. Replies and plain comments are
    never resolvable, whatever the reach."""
    if not comment.is_thread or comment.parent_comment_id is not None:
        return False
    if reach is ResolveReach.ANY:
        return True
    return reach is ResolveReach.OWN and comment.author_id is not None and comment.author_id == actor.id


async def require_resolvable(session: AsyncSession, comment: Comment, actor: User) -> None:
    reach = await resolve_reach(session, actor, comment.entity_type, comment.entity_id)
    if not reach_covers(reach, comment, actor):
        raise ForbiddenError("this project's thread rule does not let you resolve this thread")
