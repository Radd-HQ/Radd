"""The raw widget-create body → its schema. Shared by the dashboards router and the
My Work service (personal.py), which is why it is neither's: a service importing a
router helper was the RADD-1467 finding this module resolves."""

from typing import Any

import pydantic
from fastapi.exceptions import RequestValidationError

from radd.kernel import registries

from .schemas import PluginWidget, WidgetCreate
from .types import BUILTIN_WIDGET_TYPES


def parse_widget_body(body: dict[str, Any]) -> WidgetCreate | PluginWidget:
    """Dispatch a raw widget-create body to its schema: a builtin widget_type
    validates against the discriminated union (typed per-type config); a type
    registered in registries.widget_types validates as a free-form PluginWidget —
    unless it is PERSONAL (RADD-1393), which belongs on My Work only; anything
    else is unknown → 422. A pydantic shape failure is surfaced as the same
    RequestValidationError (422) FastAPI would have raised for the body."""
    widget_type = body.get("widget_type")
    spec = registries.widget_types.get(widget_type) if isinstance(widget_type, str) else None
    try:
        if widget_type in BUILTIN_WIDGET_TYPES:
            return pydantic.TypeAdapter(WidgetCreate).validate_python(body)
        if spec is not None and not spec.personal:
            return PluginWidget.model_validate(body)
    except pydantic.ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    reason = "is a My Work widget" if spec is not None else "is unknown"
    raise RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "widget_type"),
                "msg": f"widget_type {widget_type!r} {reason}",
                "input": widget_type,
            }
        ]
    )
