"""My Work: the same validated widget definitions, stored privately per user. Its
own kinds, plus every `WidgetTypeSpec(personal=True)` a plugin contributes —
offered only while that plugin is registered (RADD-1393)."""

import uuid

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import select

from radd.exceptions import ConflictError
from radd.kernel import WidgetTypeSpec, registries
from radd.modules.auth.models import User

from .schemas import PluginWidget, WidgetLayoutSave, WidgetRead
from .types import BUILTIN_WIDGET_TYPES
from .widget_bodies import parse_widget_body

TITLES = {
    "assigned": "Assigned to me",
    "due": "Due soon",
    "activity": "My activity",
    "inbox": "Inbox",
    "starred": "Starred",
    "requests": "My requests",
    "forms": "Request forms",
    "recent": "Recently viewed",
}


def contributed() -> dict[str, WidgetTypeSpec]:
    """The personal widget types the registered plugins contribute, by key."""
    return {key: spec for key, spec in registries.widget_types.items() if spec.personal}


def is_personal(widget_type: object) -> bool:
    return isinstance(widget_type, str) and (widget_type in TITLES or widget_type in contributed())


def _title(kind: str) -> str:
    return TITLES.get(kind) or registries.widget_types[kind].label


def defaults(extras=()):
    return [
        dict(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, "radd:my-work:" + kind)),
            widget_type=kind,
            title=_title(kind),
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


def _personal_widget(raw) -> PluginWidget:
    try:
        return PluginWidget.model_validate(raw)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


async def save(session, user, data: WidgetLayoutSave):
    from .widgets import _check_references, plugin_config

    await session.execute(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    stored = read(user)
    if "my_work_widgets" in (user.preferences or {}) and [
        WidgetRead.model_validate(w).model_dump(mode="json") for w in stored
    ] != [w.model_dump(mode="json") for w in data.expected]:
        raise ConflictError("dashboard", reason="My Work changed elsewhere. Reload before editing.")
    # A widget whose plugin is off right now keeps its place: the person sees the "no longer
    # available" notice, and the rest of My Work stays editable. Only a NEW one is refused.
    kept = {(str(w["id"]), w["widget_type"]) for w in stored}
    result = []
    ids = set()
    for index, raw in enumerate(data.widgets):
        widget_type = raw.get("widget_type")
        # Personal surface types have no privileged data config; every renderer uses its ordinary read API.
        orphan = widget_type not in BUILTIN_WIDGET_TYPES and widget_type not in registries.widget_types
        if is_personal(widget_type) or (orphan and (str(raw.get("id")), widget_type) in kept):
            parsed = _personal_widget(raw)
        else:
            parsed = parse_widget_body(raw)
            if isinstance(parsed, PluginWidget):
                # A contributed type's config fits its plugin's model, on My Work as anywhere.
                parsed.config = plugin_config(parsed.widget_type, parsed.config)
            else:
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
    extras = [
        key
        for key, spec in sorted(contributed().items())
        if spec.suggest is not None and await spec.suggest(session, user)
    ]
    if "forms" in registries.plugins:
        from radd.modules.forms.portal import list_portal_forms
        from radd.modules.forms.requests import list_my_requests

        if await list_my_requests(session, user, limit=1):
            extras.append("requests")
        if await list_portal_forms(session, user):
            extras.append("forms")
    return defaults(extras)
