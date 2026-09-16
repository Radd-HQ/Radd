"""Per-item activity feed (History tab / audit).

Reads the append-only event log — item field-change events (with the `changes`
diff written by `changes.py`) plus related events (comments, worklogs, web/VCS
links) whose payload `item_id` points back at the item — and returns one merged,
chronological, actor-attributed feed. Pure read over `events` (the same tolerated
inward read `reporting` uses).
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz, service as auth
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.events.service import Event
from radd.modules.fields import service as fields
from radd.modules.teams import service as teams

from .enums import ItemEntity, ItemEvent
from .schemas import HistoryActor, HistoryEntry, ItemHistory
from .service import require_readable_item

# Package-private helpers — the same per-actor field-visibility seams the item
# read path uses (RADD-834: history is an API response, not a stream consumer).
from .service.visibility import _builtin_read_denied, _field_ctx

# Related-entity event types whose payload carries `item_id` back to this item.
# Wire strings (not enum imports) so `items` doesn't take a dependency on
# comments/worklogs/weblinks/vcs — this is a read of the event stream, exactly as
# reporting reads it. Keep in sync with those modules' *Event enums.
# NOTE: csat.*, approval.*, and item.participant_* (specs 65/71/72) are emitted
# with entity_type=item DIRECTLY, so they reach the feed without an entry here.
# mail.* is the opposite case and the reason RADD-984 exists: the mail channel
# emits under entity_type=mail_intake with the item as a SUBJECT, so it could
# only ever arrive as a related type — and until it was listed, a reply that
# never reached the customer was invisible on every screen in the product.
RELATED_EVENT_TYPES: tuple[str, ...] = (
    "comment.created",
    "comment.updated",
    "comment.deleted",
    "worklog.created",
    "worklog.updated",
    "worklog.deleted",
    "weblink.created",
    "weblink.updated",
    "weblink.deleted",
    "vcs.linked",
    "vcs.updated",
    "vcs.unlinked",
    "attachment.created",
    "attachment.deleted",
    # The mail channel (RADD-960/984). `mail.dropped` is deliberately absent:
    # it names no item, by definition, so there is no feed for it to join.
    "mail.received",
    "mail.sent",
    "mail.failed",
)

_INTERNAL = "internal"

# Fields lifted from a related event's payload for the frontend's one-line summary.
_DETAIL_KEYS = (
    "visibility",
    "time_spent_seconds",
    "worked_on",
    "url",
    "title",
    "category",
    "ref_type",
    "provider",
    "status",
    "filename",
    "size_bytes",
    "rating",  # csat.responded (spec 65) — direct item events also flow through _detail
    "to_state",  # approval.* (spec 71): the gated target state's name
    "verdict",  # approval.voted: approve | decline
    "participant",  # item.participant_* (spec 72): the user/team display name
    "team",  # item.participant_*: set (a {id,name} ref) when the subject is a team
    # Mail (RADD-984). `recipients` is one address per event since RADD-1036's
    # per-message emission, but it stays a LIST on the wire — the renderer reads
    # the count, so a future batched send needs no second shape.
    "recipients",
    "recipient_count",
    "sender",  # mail.received: who wrote in
    "error",  # mail.failed: one line an operator can act on
    "given_up",  # mail.failed: the retry ladder ran out — nobody will hear from us
)


def _detail(event: Event) -> dict[str, Any] | None:
    payload = event.payload or {}
    detail = {key: payload[key] for key in _DETAIL_KEYS if key in payload}
    return detail or None


# `changes.py` diff field name -> the builtin-field rule name where they differ.
_CHANGE_FIELD_TO_BUILTIN = {"points": "estimate_points"}


def _redact_changes(
    changes: list[dict], restricted_cf: set[str], builtin_denied: set[str]
) -> list[dict]:
    """Redact — never omit — change entries whose values the actor may not read
    (RADD-834). "Priority changed" with no values is honest; dropping the entry
    would rewrite the audit trail."""
    if not restricted_cf and not builtin_denied:
        return changes
    out: list[dict] = []
    for change in changes:
        field = change.get("field")
        if field == "custom_field":
            if change.get("key") in restricted_cf:
                change = {k: change[k] for k in ("field", "key", "name") if k in change}
                change["redacted"] = True
        elif _CHANGE_FIELD_TO_BUILTIN.get(field, field) in builtin_denied:
            change = {"field": field, "redacted": True}
        out.append(change)
    return out


async def redaction_for(
    session: AsyncSession, actor: User, project
) -> tuple[set[str], set[str]]:
    """The (restricted custom-field keys, denied builtin names) an actor may
    not read in `project` — the RADD-834 seam, public since spec 123 so the
    audit log redacts item rows exactly as the History tab does."""
    permissions = await authz.effective_permissions(session, actor, project=project)
    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)
    restricted_cf = {d.key for d in definitions} - fields.readable_keys(definitions, ctx)
    builtin_denied = set(await _builtin_read_denied(session, project, ctx))
    return restricted_cf, builtin_denied


def redact_changes(
    changes: list[dict], restricted_cf: set[str], builtin_denied: set[str]
) -> list[dict]:
    """Public name for `_redact_changes` (spec 123)."""
    return _redact_changes(changes, restricted_cf, builtin_denied)


async def item_history(session: AsyncSession, item_id: uuid.UUID, actor: User) -> ItemHistory:
    item, project, permissions = await require_readable_item(session, item_id, actor)
    can_internal = Permission.COMMENT_READ_INTERNAL in permissions
    # Spec 50: teams narrow which internal-comment activity the actor may see.
    from radd.modules.comments.visibility import internal_comment_visible  # deferred: cycle

    has_manage = Permission.PROJECT_MANAGE in permissions
    actor_teams = (
        set() if has_manage else await teams.user_team_ids(session, actor.id)
    )

    # Field-level read visibility (RADD-834): the same seams the item read path
    # uses decide which change VALUES the actor may see. Cheap no-ops when no
    # read-restricting grant exists (the common case).
    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)
    restricted_cf = {d.key for d in definitions} - fields.readable_keys(definitions, ctx)
    builtin_denied = set(await _builtin_read_denied(session, project, ctx))

    raw = await events.entity_activity(
        session,
        entity_type=ItemEntity.ITEM,
        entity_id=item_id,
        related_event_types=RELATED_EVENT_TYPES,
    )
    users = await auth.users_by_ids(session, {e.actor_id for e in raw if e.actor_id})

    entries: list[HistoryEntry] = []
    for event in raw:
        payload = event.payload or {}
        # Don't leak internal-comment activity: needs comment.read_internal AND (spec 50)
        # membership in the comment's teams if it named any (author/manager bypass).
        if event.event_type.startswith("comment.") and payload.get("visibility") == _INTERNAL:
            teams_for = {uuid.UUID(t) for t in payload.get("visible_to_teams") or []}
            if not internal_comment_visible(
                is_author=event.actor_id == actor.id,
                has_read_internal=can_internal,
                has_manage=has_manage,
                comment_teams=teams_for,
                actor_teams=actor_teams,
            ):
                continue
        is_update = event.event_type == ItemEvent.UPDATED
        changes = payload.get("changes", []) if is_update else []
        # A rank-only reorder emits item.updated with no visible field change — skip.
        if is_update and not changes:
            continue
        changes = _redact_changes(changes, restricted_cf, builtin_denied)
        if event.event_type == ItemEvent.CREATED:
            detail: dict[str, Any] | None = {"title": (payload.get("item") or {}).get("title")}
        elif is_update:
            detail = None
        else:
            detail = _detail(event)
        user = users.get(event.actor_id) if event.actor_id else None
        entries.append(
            HistoryEntry(
                id=event.id,
                at=event.created_at,
                actor=HistoryActor(id=user.id, name=user.name) if user else None,
                type=str(event.event_type),
                changes=changes,
                detail=detail,
            )
        )
    return ItemHistory(entries=entries)
