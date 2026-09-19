"""Merge a duplicate into its survivor (RADD-1090).

merge(source → target): everything the duplicate accumulated — comments,
attachments, links, watchers, participants, worklogs, VCS/web/page links,
labels, service-desk thread — repoints to the target; the source becomes a
closed tombstone in its project's canceled-category state, linked
`duplicates` to the target. Worklogs keep their authors and dates: nothing
is credited to the wrong person or the wrong day.

The repoint list is EXPLICIT and RATCHETED, the spec-89 lesson
(`_MERGE_REPOINT` missed three columns and that was a latent merge bug):
`tests/test_item_merge.py` enumerates every FK to work_items from the live
schema and refuses any column no disposition here claims. Raw table names,
not model imports — the same precedent as auth's user merge, because half of
these tables belong to optional plugins items must not import.

Deliberately KEPT on the source: `search_index` and `item_embeddings` (the
tombstone is still an item and stays findable), `events` (history is what
happened, not what we wish had happened), and the source's own key aliases'
uniqueness (they repoint to the target, so every old URL lands on the
survivor).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.modules.workflow import service as workflow
from radd.modules.workflow.types import StateCategory

from ..enums import ItemEntity, ItemEvent
from ..schemas import ItemRead
from .queries import require_item
from .read import get_item
from .visibility import _check_builtin_field_rules, ensure_item_relation

MERGE_LINK_TYPE = "duplicates"


@dataclass(frozen=True)
class Repoint:
    """One item-bearing table: `dedupe_cols` are the non-item columns of a
    unique key over (item, …) — a source row whose counterpart already exists
    on the target is dropped, not collided (auth's `_dedupe_sql` idiom)."""

    table: str
    item_col: str
    dedupe_cols: tuple[str, ...] | None = None


#: Rows that MOVE. Order matters only for readability.
_REPOINT: tuple[Repoint, ...] = (
    Repoint("item_labels", "item_id", ("label_id",)),  # union
    Repoint("item_watchers", "item_id", ("user_id",)),
    Repoint("item_stars", "item_id", ("user_id",)),
    Repoint("item_participants", "item_id", ("user_id", "team_id")),
    Repoint("item_page_links", "item_id", ("page_id",)),
    Repoint("view_members", "item_id", ("view_id",)),
    Repoint("mail_contacts", "item_id", ("email",)),
    Repoint("mail_messages", "item_id"),
    Repoint("sla_item_states", "item_id", ("policy_id",)),
    Repoint("worklogs", "item_id"),
    Repoint("item_web_links", "item_id"),
    Repoint("item_vcs_links", "item_id"),
    Repoint("vcs_pending_worklogs", "item_id"),  # RADD-1258: parked MR time follows the survivor
    Repoint("item_cycle_records", "item_id"),
    Repoint("item_estimates", "item_id", ()),  # unique(item_id): target's row wins
    Repoint("csat_surveys", "item_id", ()),  # unique(item_id): target's survey wins
    Repoint("approval_requests", "item_id"),
    Repoint("alert_items", "item_id"),
    Repoint("jira_pending_refs", "source_item_id"),
    Repoint("item_key_aliases", "item_id"),  # old keys land on the survivor
    Repoint("work_items", "parent_id"),  # children re-parent to the survivor
)
#: FK columns that deliberately STAY on the tombstone.
_KEEP: frozenset[tuple[str, str]] = frozenset(
    {
        ("search_index", "item_id"),  # the tombstone remains findable
        ("item_embeddings", "item_id"),
        # item_links is handled specially below (both ends + self-link removal).
    }
)
#: Polymorphic parents (no FK): entity_type='item' + entity_id.
_POLYMORPHIC: tuple[tuple[str, str, str], ...] = (
    ("comments", "entity_type", "entity_id"),
    ("attachments", "entity_type", "entity_id"),
)


def _repoint_sql(spec: Repoint) -> list[str]:
    statements = []
    if spec.dedupe_cols is not None:
        if spec.dedupe_cols:
            match = " AND ".join(
                f"o.{col} IS NOT DISTINCT FROM t.{col}" for col in spec.dedupe_cols
            )
            statements.append(
                f"DELETE FROM {spec.table} t WHERE t.{spec.item_col} = :src AND EXISTS ("
                f"SELECT 1 FROM {spec.table} o WHERE {match} AND o.{spec.item_col} = :dst)"
            )
        else:  # unique on the item column alone — the target's row wins
            statements.append(
                f"DELETE FROM {spec.table} t WHERE t.{spec.item_col} = :src AND EXISTS ("
                f"SELECT 1 FROM {spec.table} o WHERE o.{spec.item_col} = :dst)"
            )
    statements.append(
        f"UPDATE {spec.table} SET {spec.item_col} = :dst WHERE {spec.item_col} = :src"
    )
    return statements


async def merge_items(
    session: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID, actor: User
) -> ItemRead:
    """Keep every repoint atomic even when a caller catches a late refusal."""
    async with session.begin_nested():
        return await _merge_items(session, source_id, target_id, actor)


async def _merge_items(
    session: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID, actor: User
) -> ItemRead:
    if source_id == target_id:
        raise ConflictError(ItemEntity.ITEM, reason="an item cannot merge into itself")
    source = await require_item(session, source_id)
    target = await require_item(session, target_id)
    if source.kind != target.kind:
        raise ConflictError(
            ItemEntity.ITEM,
            reason=f"kinds differ ({source.kind} → {target.kind}) — convert one first",
        )
    source_project = await projects_service.get_project(session, source.project_id)
    target_project = await projects_service.get_project(session, target.project_id)
    source_permissions = await authz.require(
        session, actor, Permission.ITEM_UPDATE, project=source_project
    )
    target_permissions = await authz.require(
        session, actor, Permission.ITEM_UPDATE, project=target_project
    )
    await ensure_item_relation(session, actor, source, source_permissions, Permission.ITEM_UPDATE)
    await ensure_item_relation(session, actor, target, target_permissions, Permission.ITEM_UPDATE)
    # Moving a private discussion into another project's audience is not an
    # ordinary update. Keep this operation within one permission boundary.
    if source_project.id != target_project.id:
        raise ConflictError(ItemEntity.ITEM, reason="merge requires items in the same project")
    await _check_builtin_field_rules(
        session, actor, source_project, source_permissions, {"state_id"}
    )

    await _check_builtin_field_rules(
        session, actor, target_project, target_permissions, {"labels"}
    )

    # The tombstone state must exist before anything moves.
    states = await workflow.list_states(session, source_project.id)
    canceled = next((s for s in states if s.category == StateCategory.CANCELED), None)
    if canceled is None:
        raise ConflictError(
            ItemEntity.ITEM,
            reason=f"project {source_project.key} has no canceled-category state to "
            "close the duplicate into",
        )

    source_key = f"{source_project.key}-{source.number}"
    target_key = f"{target_project.key}-{target.number}"

    for spec in _REPOINT:
        for statement in _repoint_sql(spec):
            await session.execute(text(statement), {"src": str(source.id), "dst": str(target.id)})
    for table, type_col, id_col in _POLYMORPHIC:
        await session.execute(
            text(
                f"UPDATE {table} SET {id_col} = :dst "
                f"WHERE {type_col} = 'item' AND {id_col} = :src"
            ),
            {"src": str(source.id), "dst": str(target.id)},
        )

    # Links: repoint both ends, then drop self-links and duplicates.
    for col, other in (("source_item_id", "target_item_id"), ("target_item_id", "source_item_id")):
        await session.execute(
            text(
                f"DELETE FROM item_links t WHERE t.{col} = :src AND (t.{other} = :dst OR EXISTS ("
                f"SELECT 1 FROM item_links o WHERE o.{col} = :dst "
                f"AND o.{other} = t.{other} AND o.link_type = t.link_type))"
            ),
            {"src": str(source.id), "dst": str(target.id)},
        )
        await session.execute(
            text(f"UPDATE item_links SET {col} = :dst WHERE {col} = :src"),
            {"src": str(source.id), "dst": str(target.id)},
        )

    # The tombstone: canceled state + the duplicates link that explains it.
    # The transition runs the project's guards (spec 107) like any other —
    # a merge must not apply a close the workflow would refuse (RADD-1071).
    old_state_id = source.state_id
    source.state_id = canceled.id
    await workflow.check_transition(session, source_project, source, old_state_id, canceled.id)
    await session.execute(
        text(
            "INSERT INTO item_links (id, source_item_id, target_item_id, link_type) "
            "VALUES (:id, :src, :dst, :lt) ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(uuid.uuid4()),
            "src": str(source.id),
            "dst": str(target.id),
            "lt": MERGE_LINK_TYPE,
        },
    )
    await session.flush()

    for item_id, changes in (
        (source.id, [{"field": "merged_into", "from": None, "to": target_key}]),
        (target.id, [{"field": "merged_from", "from": None, "to": source_key}]),
    ):
        await events.emit(
            session,
            event_type=ItemEvent.UPDATED,
            entity_type=ItemEntity.ITEM,
            entity_id=item_id,
            actor_id=actor.id,
            subjects={"item": item_id},
            changes=changes,
        )
    return await get_item(session, target.id, actor)
