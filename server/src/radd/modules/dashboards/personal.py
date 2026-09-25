"""My Work uses the same validated widget definitions, privately stored per user."""

import uuid

from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from sqlalchemy import select
from .schemas import WidgetLayoutSave, WidgetRead

PERSONAL_TYPES = {
    "assigned",
    "due",
    "activity",
    "inbox",
    "starred",
    "approvals",
    "requests",
    "forms",
    "recent",
}
TITLES = {
    "assigned": "Assigned to me",
    "due": "Due soon",
    "activity": "My activity",
    "inbox": "Inbox",
    "starred": "Starred",
    "approvals": "Awaiting my approval",
    "requests": "My requests",
    "forms": "Request forms",
    "recent": "Recently viewed",
}


def defaults(extras=()):
    return [
        dict(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, "radd:my-work:" + kind)),
            widget_type=kind,
            title=TITLES[kind],
            width=width,
            height=height,
            collapsed=False,
            position=i,
            config={},
        )
        for i, (kind, width, height) in enumerate(
            [
                ("assigned", 8, 360),
                ("due", 4, 360),
                ("activity", 8, 360),
                ("inbox", 4, 360),
                ("starred", 4, 280),
            ]
            + [(kind, 4, 280) for kind in extras]
        )
    ]


def read(user):
    return (user.preferences or {}).get("my_work_widgets", defaults())


async def save(session, user, data: WidgetLayoutSave):
    from .router import _parse_widget_body
    from .widgets import _check_references

    await session.execute(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if "my_work_widgets" in (user.preferences or {}) and [
        WidgetRead.model_validate(w).model_dump(mode="json") for w in read(user)
    ] != [w.model_dump(mode="json") for w in data.expected]:
        raise ConflictError("dashboard", reason="My Work changed elsewhere. Reload before editing.")
    result = []
    ids = set()
    for index, raw in enumerate(data.widgets):
        # Personal surface types have no privileged data config; every renderer uses its ordinary read API.
        if raw.get("widget_type") in PERSONAL_TYPES:
            from .schemas import PluginWidget

            from fastapi.exceptions import RequestValidationError
            from pydantic import ValidationError

            try:
                parsed = PluginWidget.model_validate(raw)
            except ValidationError as exc:
                raise RequestValidationError(exc.errors()) from exc
        else:
            parsed = _parse_widget_body(raw)
            if hasattr(parsed.config, "model_dump"):
                await _check_references(session, user, None, parsed.config)
        row = {**parsed.model_dump(mode="json"), "id": str(uuid.UUID(raw["id"])), "position": index}
        if row["id"] in ids:
            raise ConflictError("dashboard", reason="Duplicate widget id")
        ids.add(row["id"])
        result.append(row)
    user.preferences = {**(user.preferences or {}), "my_work_widgets": result}
    await session.flush()
    return result


async def suggested_defaults(session, user):
    from radd.kernel import registries

    extras = []
    if "approvals" in registries.plugins:
        from radd.modules.approvals.service import pending_for_user

        if await pending_for_user(session, user):
            extras.append("approvals")
    if "forms" in registries.plugins:
        from radd.modules.forms.portal import list_portal_forms
        from radd.modules.forms.requests import list_my_requests

        if await list_my_requests(session, user, limit=1):
            extras.append("requests")
        if await list_portal_forms(session, user):
            extras.append("forms")
    return defaults(extras)
