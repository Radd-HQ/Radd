"""Live OpenAPI: the registry projected into every schema that carries the marker."""

from dataclasses import dataclass, field
from typing import Any

from .models import FieldDefinition
from .types import FieldType

# Schemas opt in by setting this key in json_schema_extra on their custom_fields property.
CUSTOM_FIELDS_MARKER = "x-radd-custom-fields"


@dataclass
class SchemaCache:
    """Process-wide snapshot of the registry, refreshed on startup and field mutations."""

    properties: dict[str, Any] = field(default_factory=dict)


schema_cache = SchemaCache()


def _property_schema(definition: FieldDefinition, restricted: bool = False) -> dict[str, Any]:
    field_type = FieldType(definition.type)
    base: dict[str, Any] = {"title": definition.name}
    match field_type:
        case FieldType.TEXT | FieldType.USER:
            base |= {"type": "string"}
        case FieldType.URL:
            base |= {"type": "string", "format": "uri"}
        case FieldType.NUMBER:
            base |= {"type": "number"}
        case FieldType.BOOLEAN:
            base |= {"type": "boolean"}
        case FieldType.DATE:
            base |= {"type": "string", "format": "date"}
        case FieldType.DURATION:
            base |= {"type": "integer", "minimum": 0, "description": "minutes"}
        case FieldType.SELECT:
            base |= {"type": "string", "enum": definition.options}
        case FieldType.MULTI_SELECT:
            base |= {"type": "array", "items": {"type": "string", "enum": definition.options}}
    if definition.required:
        base["x-required"] = True
    if definition.default_value is not None:
        base["default"] = definition.default_value
    # Field-level visibility hint (spec 07/92): the field carries access grants, so
    # some actors won't see it / can't write it. Grant details stay API-only.
    if restricted:
        base["x-restricted"] = True
    return base


def refresh(definitions: list[FieldDefinition], restricted_keys: set[str] = frozenset()) -> None:
    schema_cache.properties = {
        d.key: _property_schema(d, d.key in restricted_keys) for d in definitions
    }


def augment_openapi(schema: dict[str, Any]) -> None:
    for component in schema.get("components", {}).get("schemas", {}).values():
        properties = component.get("properties", {})
        current = properties.get("custom_fields")
        if isinstance(current, dict) and current.get(CUSTOM_FIELDS_MARKER):
            properties["custom_fields"] = {
                CUSTOM_FIELDS_MARKER: True,
                "type": "object",
                "additionalProperties": False,
                "properties": schema_cache.properties,
            }
