"""Personal activity reveals only current readable subjects, never raw event payloads."""

import uuid
from radd.exceptions import ForbiddenError, NotFoundError
from datetime import UTC
from radd.modules.events import service as events_service
from radd.modules.events.types import EventSource
from radd.kernel import registries
from radd.modules.items.service import require_readable_item

ACTIONS = {
    "item.created": "Created issue",
    "item.updated": "Updated issue",
    "item.transitioned": "Changed state",
    "comment.created": "Commented",
    "comment.updated": "Edited comment",
    "comment.resolved": "Resolved thread",
    "comment.reopened": "Reopened thread",
    "worklog.created": "Logged work",
    "worklog.updated": "Updated work log",
}


async def read(session, user, *, before=None, project_id=None, start=None, end=None, limit=10):
    events = await events_service.query_events(
        session,
        actor_id=user.id,
        event_types=list(ACTIONS),
        source=EventSource.PEOPLE,
        before_id=before,
        project_id=project_id,
        start=start.astimezone(UTC).replace(tzinfo=None) if start and start.tzinfo else start,
        end=end.astimezone(UTC).replace(tzinfo=None) if end and end.tzinfo else end,
        limit=200,
    )
    readable = {}
    result = []
    last = None
    for event in events:
        last = event.id
        try:
            item_ref = (event.payload or {}).get("item") or {}
            item_id = uuid.UUID(
                event.entity_id if event.entity_type == "item" else item_ref.get("id", "")
            )
            if item_id not in readable:
                readable[item_id] = await require_readable_item(session, item_id, user)
            item, project, _ = readable[item_id]
            if event.event_type == "item.updated" and not (event.payload or {}).get("changes"):
                continue
            comment_id = None
            if event.event_type.startswith("comment."):
                if "comments" not in registries.plugins:
                    continue
                from radd.modules.comments import service as comments

                location = await comments.locate(session, uuid.UUID(event.entity_id), user)
                if location.entity_type != "item" or location.entity_id != item.id:
                    continue
                comment_id = event.entity_id
            # Deliberately omit historical titles, field values and comment text: current field restrictions may differ.
            result.append(
                dict(
                    id=event.id,
                    at=event.created_at.isoformat() + "Z",
                    action=(
                        "Changed state"
                        if event.event_type == "item.updated"
                        and any(
                            c.get("field") == "state"
                            for c in (event.payload or {}).get("changes", [])
                        )
                        else ACTIONS[event.event_type]
                    ),
                    item_key=f"{project.key}-{item.number}",
                    comment_id=comment_id,
                )
            )
        except (NotFoundError, ForbiddenError, ValueError, TypeError):
            continue
        if len(result) == limit:
            break
    has_more = bool(events) and (
        len(events) == 200 or len(result) == limit and last != events[-1].id
    )
    return {"entries": result, "next": last if has_more else None}
