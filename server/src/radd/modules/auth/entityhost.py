"""auth's implementation of the kernel's `EntityHost` (RADD-892): caller
resolution, `authz.require` and the relation-aware row filter for generated
CRUD. Installed at import — module state, so `registries.clear()` cannot wipe it."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import UnauthorizedError
from radd.kernel import hosts
from radd.kernel.registry import registries

from . import authz
from .deps import optional_user

logger = logging.getLogger(__name__)

#: (entity_key, relation_key) pairs already reported — one line per pair per
#: process, not one per row of every listing (RADD-1040).
_query_gated_warned: set[tuple[str, str]] = set()


def _warn_query_gated(entity_key: str, relations: frozenset[str]) -> None:
    """Log once per (entity, relation) what the SYNC row gate drops (RADD-1040):
    generated CRUD cannot await a query-gated relation (`holds=None`), so rows only
    it would admit stay hidden — correctly, but silently without this."""
    from .types import relation_contains

    for key, spec in registries.relations_for(entity_key).items():
        if spec.holds is not None:
            continue
        if not any(relation_contains(held, key) for held in relations):
            continue
        pair = (entity_key, key)
        if pair in _query_gated_warned:
            continue
        _query_gated_warned.add(pair)
        logger.warning(
            "generated CRUD for entity '%s' cannot honour relation @%s (%r): it is "
            "query-gated (holds=None), and the generated row filter supports only "
            "PURE relations — rows this relation alone would grant are hidden. Give "
            "the relation a pure `holds` form, or serve the entity from a hand-written "
            "router that can await the database.",
            entity_key,
            key,
            spec.label,
        )


class AuthEntityHost:
    async def readable_project_ids(self, session, user, entity_key):
        reach = await authz.readable_projects(session, user)
        has_relations = bool(registries.relations_for(entity_key))
        return [project_id for project_id, permissions in reach.items()
                if has_relations or authz.RELATION_ANY in authz.relations_held(permissions, authz.Permission.ITEM_READ)]

    async def current_user(self, request: Any, session: AsyncSession) -> Any:
        user = await optional_user(request, session)
        if user is None:
            raise UnauthorizedError()
        return user

    async def require(
        self, session: AsyncSession, user: Any, atom: str, *, project_id: Any | None
    ) -> None:
        if project_id is None:
            await authz.require(session, user, atom)
            return
        from radd.modules.projects import service as projects_service

        project = await projects_service.get_project(session, project_id)
        await authz.require(session, user, atom, project=project)

    async def visible_rows(
        self, session: AsyncSession, user: Any, entity_key: str, rows: list[Any]
    ) -> list[Any]:
        """item.read on each row's project, then the RADD-817 relation narrowing
        through the SYNC row gate. `relation_actor` is resolved lazily, once."""
        from radd.modules.projects import service as projects_service

        entity_relations = registries.relations_for(entity_key)
        relation_actor = None
        # Relation sets already reported on in THIS call — the process-wide guard
        # inside the helper would still make it a dict scan per row.
        reported: set[frozenset[str]] = set()
        visible = []
        for obj in rows:
            project = await projects_service.get_project(session, obj.project_id)
            perms = await authz.effective_permissions(session, user, project=project)
            if not authz.holds_base(perms, authz.Permission.ITEM_READ):
                continue
            relations = authz.relations_held(perms, authz.Permission.ITEM_READ)
            if authz.RELATION_ANY not in relations and not entity_relations:
                # RADD-1327: a NARROWED read grants a row only through a relation the
                # entity defines; `holds_base` alone let every member list every
                # project's milestones.
                continue
            if entity_relations:
                if authz.RELATION_ANY not in relations:
                    if relation_actor is None:
                        relation_actor = await authz.relation_actor(session, user)
                    if relations not in reported:
                        reported.add(relations)
                        _warn_query_gated(entity_key, relations)
                    if not authz.relation_holds_row(
                        entity_key, relations, relation_actor, obj
                    ):
                        continue
            visible.append(obj)
        return visible

    async def emit(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        entity_type: str,
        entity_id: Any,
        actor_id: Any,
        payload: dict[str, Any] | None = None,
        subjects: dict[str, Any] | None = None,
        changes: list[dict[str, Any]] | None = None,
    ) -> None:
        from radd.modules.events import service as events

        await events.emit(
            session,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            payload=payload,
            subjects=subjects,
            changes=changes,
        )


hosts.set_entity_host(AuthEntityHost())
