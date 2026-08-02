"""Custom-field compilation: JSONB operators typed by the registry definition.

Equality goes through `@>` containment (GIN-friendly, matches the `cf` param's
spec-08 semantics); ranges/`~`/IN through `->>` with per-type casts. Scalar `!=`
means "has a different value" (missing keys compare as SQL NULL -> excluded);
multi_select `!=` means "lacks" (missing included) — mirroring `label`.
"""

from typing import Any

from sqlalchemy import ColumnElement, Date, Numeric, not_, or_

from radd.modules.fields.models import FieldDefinition
from radd.modules.fields.types import FieldType

from ..models import WorkItem
from .catalog import CF_OPS
from .errors import SlqError, unknown_field
from .helpers import (
    LIKE_ESCAPE,
    Context,
    check_ops,
    compare,
    date_value,
    escape_like,
    plain,
    polarity,
    values_of,
)
from .lexer import CompareOp
from .parser import Comparison, Condition, EmptyCheck, Membership, Value

EMPTY_JSON_ARRAY = "[]"

BOOLEAN_WORDS = {"true": True, "false": False}


def cf_scalar(definition: FieldDefinition, value: Value, field: str) -> Any:
    """Coerce a query value to the JSON shape the field stores."""
    field_type = FieldType(definition.type)
    if field_type in (FieldType.NUMBER, FieldType.DURATION):
        try:
            return int(value.text)
        except ValueError:
            try:
                return float(value.text)
            except ValueError:
                raise SlqError(
                    f"field '{field}' expects a number, got '{value.text}'", value.position
                ) from None
    if field_type is FieldType.BOOLEAN:
        if value.text not in BOOLEAN_WORDS:
            raise SlqError(
                f"field '{field}' expects true or false, got '{value.text}'", value.position
            )
        return BOOLEAN_WORDS[value.text]
    if field_type is FieldType.DATE:
        return date_value(value, field).isoformat()
    return plain(value, field)


def custom_condition(ctx: Context, node: Condition) -> ColumnElement[bool]:
    definition = ctx.definitions_by_key.get(node.field)
    if definition is None:
        raise unknown_field(node.field, node.field_position, ctx.field_names)
    field_type = FieldType(definition.type)
    check_ops(node, CF_OPS[field_type])
    json_value = WorkItem.custom_fields[definition.key]

    if isinstance(node, EmptyCheck):
        empty = json_value.astext.is_(None)
        if field_type is FieldType.MULTI_SELECT:
            empty = or_(empty, json_value.astext == EMPTY_JSON_ARRAY)
        return not_(empty) if node.negated else empty

    if field_type is FieldType.MULTI_SELECT:  # containment: = contains, != lacks
        contains_any = or_(
            *(
                WorkItem.custom_fields.contains({definition.key: [plain(v, node.field)]})
                for v in values_of(node)
            )
        )
        return polarity(node, contains_any)

    if isinstance(node, Membership):
        texts = [str(cf_scalar(definition, v, node.field)) for v in values_of(node)]
        return polarity(node, json_value.astext.in_(texts))

    assert isinstance(node, Comparison)
    if node.op is CompareOp.CONTAINS:
        text = plain(node.value, node.field)
        return json_value.astext.ilike(f"%{escape_like(text)}%", escape=LIKE_ESCAPE)
    coerced = cf_scalar(definition, node.value, node.field)
    if field_type in (FieldType.NUMBER, FieldType.DURATION):
        return compare(json_value.astext.cast(Numeric), node.op, coerced)
    if field_type is FieldType.DATE:
        return compare(json_value.astext.cast(Date), node.op, coerced)
    if node.op is CompareOp.EQ:
        return WorkItem.custom_fields.contains({definition.key: coerced})
    # != on scalars: has a value and it differs (missing keys compare as NULL -> excluded)
    if field_type is FieldType.BOOLEAN:
        return WorkItem.custom_fields.contains({definition.key: not coerced})
    return json_value.astext != str(coerced)
