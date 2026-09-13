import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ConflictError
from radd.modules.auth.deps import Actor, CurrentUser
from radd.modules.workflow.types import StateCategory

from . import bulk, rollup, service
from .enums import ItemEntity, ItemKind, Priority
from .filters import NONE_LITERAL, ItemListFilters
from .history import item_history
from .schemas import (
    BulkMoveResult,
    BulkUpdateResult,
    ItemBulkMove,
    ItemBulkUpdate,
    ItemCount,
    ItemCreate,
    ItemHistory,
    ItemIds,
    ItemClone,
    ItemConvert,
    ItemMerge,
    ItemLinkCreate,
    ItemLinkSearchResult,
    ItemRankUpdate,
    ItemRead,
    ItemRollup,
    ItemRollupRequest,
    ItemUpdate,
    SlqValidation,
)
from .slq import suggest as slq_suggest
from .slq.suggest import SuggestResponse

router = APIRouter(prefix="/items", tags=["items"])

Session = Annotated[AsyncSession, Depends(get_session)]

# Repeatable filter params (spec 08): repeats within a param OR, params AND.
# Names match ItemFilterParam — the contract saved views compose against.
_ID_OR_NONE_DOC = f"UUID or the literal '{NONE_LITERAL}' (unset); repeatable"
_CF_DOC = "custom-field filter 'key:value' (multi_select: containment); repeatable"
_Q_DOC = (
    "SLQ query (spec 10), e.g. `label = urgent AND state != Done ORDER BY priority DESC`; "
    "ANDed with the structured params. Invalid -> 422 {detail, position}."
)


@router.post("", response_model=ItemRead, status_code=201)
async def create_item(data: ItemCreate, session: Session, user: CurrentUser) -> ItemRead:
    return await service.create_item(session, data, actor=user)


@router.get("", response_model=list[ItemRead])
async def list_items(
    session: Session,
    user: Actor,
    q: Annotated[str | None, Query(description=_Q_DOC)] = None,
    project_id: uuid.UUID | None = None,
    state_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    category: Annotated[list[StateCategory] | None, Query()] = None,
    kind: Annotated[list[ItemKind] | None, Query()] = None,
    priority: Annotated[list[Priority] | None, Query()] = None,
    parent_id: uuid.UUID | None = None,
    assignee_id: Annotated[list[str] | None, Query(description=_ID_OR_NONE_DOC)] = None,
    team_id: Annotated[list[str] | None, Query(description=_ID_OR_NONE_DOC)] = None,
    cycle_id: Annotated[list[str] | None, Query(description=_ID_OR_NONE_DOC)] = None,
    label: Annotated[list[str] | None, Query(description="label name; repeatable")] = None,
    cf: Annotated[list[str] | None, Query(description=_CF_DOC)] = None,
    archived: Annotated[bool, Query(description="true = archived items ONLY (spec 38)")] = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ItemRead]:
    filters = ItemListFilters(
        project_id=project_id,
        state_ids=tuple(state_id or ()),
        categories=tuple(category or ()),
        kinds=tuple(kind or ()),
        priorities=tuple(priority or ()),
        parent_id=parent_id,
        assignee_ids=tuple(assignee_id or ()),
        team_ids=tuple(team_id or ()),
        cycle_ids=tuple(cycle_id or ()),
        labels=tuple(label or ()),
        cf=tuple(cf or ()),
        archived=archived,
    )
    return await service.list_items(
        session, actor=user, filters=filters, q=q, limit=limit, offset=offset
    )


_VALIDATE_DOC = (
    "Parse + compile an SLQ draft WITHOUT executing it — the editors' live validation. "
    "Valid or blank -> {ok: true}; invalid -> 422 {detail, position}."
)


@router.get("/slq/validate", response_model=SlqValidation, description=_VALIDATE_DOC)
async def validate_slq(
    session: Session,
    user: Actor,
    q: str = "",
    project_id: uuid.UUID | None = None,
) -> SlqValidation:
    await service.validate_slq(session, actor=user, q=q, project_id=project_id)
    return SlqValidation()


_SUGGEST_DOC = (
    "SLQ autocomplete (spec 12): context + ranked suggestions for the cursor position. "
    "`insert` splices verbatim over [replace_from, cursor); `cursor` defaults to len(q)."
)


@router.get("/slq/suggest", response_model=SuggestResponse, description=_SUGGEST_DOC)
async def suggest_slq(
    session: Session,
    user: Actor,
    q: str = "",
    cursor: Annotated[int | None, Query(ge=0)] = None,
    project_id: uuid.UUID | None = None,
) -> SuggestResponse:
    return await slq_suggest.suggest(
        session,
        actor=user,
        project_id=project_id,
        q=q,
        cursor=cursor,
    )


@router.get("/ids", response_model=ItemIds)
async def list_item_ids(
    session: Session,
    user: Actor,
    q: Annotated[str | None, Query(description=_Q_DOC)] = None,
    project_id: uuid.UUID | None = None,
    state_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    category: Annotated[list[StateCategory] | None, Query()] = None,
    kind: Annotated[list[ItemKind] | None, Query()] = None,
    priority: Annotated[list[Priority] | None, Query()] = None,
    parent_id: uuid.UUID | None = None,
    assignee_id: Annotated[list[str] | None, Query(description=_ID_OR_NONE_DOC)] = None,
    team_id: Annotated[list[str] | None, Query(description=_ID_OR_NONE_DOC)] = None,
    cycle_id: Annotated[list[str] | None, Query(description=_ID_OR_NONE_DOC)] = None,
    label: Annotated[list[str] | None, Query(description="label name; repeatable")] = None,
    cf: Annotated[list[str] | None, Query(description=_CF_DOC)] = None,
    archived: Annotated[bool, Query(description="true = archived items ONLY")] = False,
) -> ItemIds:
    """Ids of every visible item matching the filter (spec 68) — the 'select all
    N matching' seam. ids capped at bulk_max_items, total is the true count."""
    filters = ItemListFilters(
        project_id=project_id,
        state_ids=tuple(state_id or ()),
        categories=tuple(category or ()),
        kinds=tuple(kind or ()),
        priorities=tuple(priority or ()),
        parent_id=parent_id,
        assignee_ids=tuple(assignee_id or ()),
        team_ids=tuple(team_id or ()),
        cycle_ids=tuple(cycle_id or ()),
        labels=tuple(label or ()),
        cf=tuple(cf or ()),
        archived=archived,
    )
    return await bulk.list_item_ids(session, actor=user, filters=filters, q=q)


@router.get("/count", response_model=ItemCount)
async def count_items(
    session: Session,
    user: Actor,
    q: Annotated[str | None, Query(description=_Q_DOC)] = None,
    project_id: uuid.UUID | None = None,
    state_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    category: Annotated[list[StateCategory] | None, Query()] = None,
    kind: Annotated[list[ItemKind] | None, Query()] = None,
    priority: Annotated[list[Priority] | None, Query()] = None,
    parent_id: uuid.UUID | None = None,
    assignee_id: Annotated[list[str] | None, Query(description=_ID_OR_NONE_DOC)] = None,
    team_id: Annotated[list[str] | None, Query(description=_ID_OR_NONE_DOC)] = None,
    cycle_id: Annotated[list[str] | None, Query(description=_ID_OR_NONE_DOC)] = None,
    label: Annotated[list[str] | None, Query(description="label name; repeatable")] = None,
    cf: Annotated[list[str] | None, Query(description=_CF_DOC)] = None,
    archived: Annotated[bool, Query(description="true = archived items ONLY")] = False,
) -> ItemCount:
    """The visible-match count alone (spec 75): same filter surface + visibility
    as GET /items/ids, `{total}` only — powers the dashboard slq_count widgets."""
    filters = ItemListFilters(
        project_id=project_id,
        state_ids=tuple(state_id or ()),
        categories=tuple(category or ()),
        kinds=tuple(kind or ()),
        priorities=tuple(priority or ()),
        parent_id=parent_id,
        assignee_ids=tuple(assignee_id or ()),
        team_ids=tuple(team_id or ()),
        cycle_ids=tuple(cycle_id or ()),
        labels=tuple(label or ()),
        cf=tuple(cf or ()),
        archived=archived,
    )
    return ItemCount(total=await bulk.count_items(session, actor=user, filters=filters, q=q))


@router.post("/bulk-update", response_model=BulkUpdateResult)
async def bulk_update_items(
    data: ItemBulkUpdate, session: Session, user: CurrentUser
) -> BulkUpdateResult:
    """Apply one patch to many items (spec 68). Per-item authz/guards apply;
    failures are skipped and reported, never failing the batch."""
    return await bulk.bulk_update_items(session, data, actor=user)


@router.post("/bulk-move", response_model=BulkMoveResult)
async def bulk_move_items(
    data: ItemBulkMove, session: Session, user: CurrentUser
) -> BulkMoveResult:
    """Move items (and their descendants) to another project (spec 68): re-keys
    via the target counter, maps state/type by name, clears releases, drops
    custom fields absent from the target scope, and records key aliases."""
    return await bulk.bulk_move_items(session, data, actor=user)


@router.post("/rollup", response_model=dict[uuid.UUID, ItemRollup])
async def rollup_items(
    data: ItemRollupRequest, session: Session, user: CurrentUser
) -> dict[uuid.UUID, ItemRollup]:
    """Epic progress for a page of items (spec 76): descendant counts/points by
    state category + estimate/logged time, computed over children AND
    grandchildren in one query wave per depth level. The request is filtered to
    items the actor can read (unreadable ids omitted, mirroring sla/batch)."""
    return await rollup.rollup_items(session, user, data.item_ids)


@router.get("/link-search", response_model=list[ItemLinkSearchResult])
async def link_search(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID,
    q: str = "",
    exclude_id: uuid.UUID | None = None,
    limit: int = Query(8, ge=1, le=25),
) -> list[ItemLinkSearchResult]:
    """Typeahead candidates for the dependency add-row and parent picker (match by
    title or number/key) — across projects, same-project matches first (spec 80)."""
    return await service.link_search(
        session, project_id=project_id, q=q, actor=user, limit=limit, exclude_id=exclude_id
    )


@router.get("/by-key/{key}", response_model=ItemRead)
async def get_item_by_key(key: str, session: Session, user: Actor) -> ItemRead:
    """Resolve an item by its canonical key (`TD-1234`) — powers `/issues/{key}` URLs."""
    return await service.get_item_by_key(session, key, actor=user)


@router.get("/{item_id}", response_model=ItemRead)
async def get_item(item_id: uuid.UUID, session: Session, user: Actor) -> ItemRead:
    return await service.get_item(session, item_id, actor=user)


@router.get("/{item_id}/history", response_model=ItemHistory)
async def get_item_history(item_id: uuid.UUID, session: Session, user: Actor) -> ItemHistory:
    """Chronological, actor-attributed activity feed: field changes + comments,
    worklogs, and links on the item (the History tab)."""
    return await item_history(session, item_id, actor=user)


@router.patch("/{item_id}", response_model=ItemRead)
async def update_item(
    item_id: uuid.UUID, data: ItemUpdate, session: Session, user: CurrentUser
) -> ItemRead:
    return await service.update_item(session, item_id, data, actor=user)


@router.post("/{item_id}/clone", response_model=ItemRead, status_code=201)
async def clone_item(
    item_id: uuid.UUID, data: ItemClone, session: Session, user: CurrentUser
) -> ItemRead:
    """Clone this item (RADD-1088): copies content and shape, never trail —
    lands in the initial state, linked `relates` to the original."""
    return await service.clone_item(
        session, item_id, user, title=data.title, include_subtasks=data.include_subtasks
    )


@router.post("/{item_id}/convert", response_model=ItemRead)
async def convert_item(
    item_id: uuid.UUID, data: ItemConvert, session: Session, user: CurrentUser
) -> ItemRead:
    """Convert kind (RADD-1089): epic <-> issue <-> subtask, refusing with the
    blocker's name when the hierarchy would break."""
    kwargs = {}
    if "parent_id" in data.model_fields_set:
        kwargs["parent_id"] = data.parent_id
    return await service.convert_item_kind(session, item_id, user, kind=data.kind, **kwargs)


@router.post("/{item_id}/merge", response_model=ItemRead)
async def merge_item(
    item_id: uuid.UUID, data: ItemMerge, session: Session, user: CurrentUser
) -> ItemRead:
    """Merge this duplicate into the survivor (RADD-1090): comments, links,
    watchers, worklogs and the service-desk thread repoint; this item closes
    canceled with a `duplicates` link. Returns the SURVIVOR."""
    if (data.target_id is None) == (data.target_key is None):
        raise ConflictError(ItemEntity.ITEM, reason="pass exactly one of target_id or target_key")
    target_id = data.target_id
    if target_id is None:
        target = await service.get_item_by_key(session, str(data.target_key), actor=user)
        target_id = target.id
    return await service.merge_items(session, item_id, target_id, actor=user)


@router.post("/{item_id}/links", response_model=ItemRead, status_code=201)
async def add_item_link(
    item_id: uuid.UUID, data: ItemLinkCreate, session: Session, user: CurrentUser
) -> ItemRead:
    """Link this item to another (blocks/relates/duplicates)."""
    return await service.add_item_link(session, item_id, data, actor=user)


@router.delete("/{item_id}/links/{link_id}", status_code=204)
async def remove_item_link(
    item_id: uuid.UUID, link_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    await service.remove_item_link(session, item_id, link_id, actor=user)


@router.patch("/{item_id}/rank", response_model=ItemRead)
async def reorder_item(
    item_id: uuid.UUID, data: ItemRankUpdate, session: Session, user: CurrentUser
) -> ItemRead:
    """Set an item's manual rank between two neighbours (drag-to-rank, spec 24)."""
    return await service.reorder_item(session, item_id, data, actor=user)


@router.put("/{item_id}/star", response_model=ItemRead)
async def star_item(item_id: uuid.UUID, session: Session, user: CurrentUser) -> ItemRead:
    """Personal star (spec 24) — idempotent; visible only to you."""
    return await service.star_item(session, item_id, actor=user)


@router.delete("/{item_id}/star", status_code=204)
async def unstar_item(item_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.unstar_item(session, item_id, actor=user)


@router.put("/{item_id}/archive", response_model=ItemRead)
async def archive_item(item_id: uuid.UUID, session: Session, user: CurrentUser) -> ItemRead:
    """Soft archive (spec 38): hidden from lists/boards by default."""
    return await service.set_archived(session, item_id, True, user)


@router.delete("/{item_id}/archive", response_model=ItemRead)
async def unarchive_item(item_id: uuid.UUID, session: Session, user: CurrentUser) -> ItemRead:
    return await service.set_archived(session, item_id, False, user)


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    """Hard delete (spec 38): gated on item.delete (spec 50 — project.manage
    implies it); children must be removed first. The event log keeps the
    item's history."""
    await service.delete_item(session, item_id, user)
