"""Typed parsing of the repeatable `GET /items` filter params (spec 08).

`ItemFilterParam` is the canonical set of query-param names. The views module
composes each saved view's `query_string` from exactly these params (spec 10:
`q` + `project_id` — `views/service.py:_read`); `demo_views.sh` proves the
round-trip end to end.

Semantics: values repeated within one param are OR-ed (`state_id=a&state_id=b`
-> state IN (a, b)); different params are AND-ed. `cf` params are each their
own AND condition. The `q` SLQ query (items/slq/) ANDs on top of all of them.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from radd.exceptions import RaddError
from radd.modules.fields.models import FieldDefinition
from radd.modules.fields.types import FieldType
from radd.modules.workflow.types import StateCategory

from .enums import ItemKind, Priority

# Literal accepted by assignee_id/team_id meaning "the relation is unset".
NONE_LITERAL = "none"
# `cf` param format: "<key>:<value>", split on the FIRST separator (values may contain it).
CF_SEPARATOR = ":"


class ItemFilterParam(StrEnum):
    """Query-param names of `GET /items` — the contract saved views compose against."""

    Q = "q"  # SLQ query text (spec 10) — ANDed with every structured param below
    PROJECT_ID = "project_id"
    STATE_ID = "state_id"
    CATEGORY = "category"
    KIND = "kind"
    PRIORITY = "priority"
    ASSIGNEE_ID = "assignee_id"
    TEAM_ID = "team_id"
    CYCLE_ID = "cycle_id"
    LABEL = "label"
    CF = "cf"


class FilterParseError(RaddError):
    """Malformed filter value (-> 422 via the items module exception handler)."""


@dataclass(frozen=True)
class ItemListFilters:
    """The `GET /items` filter params, one attribute per `ItemFilterParam`.

    `assignee_ids`/`team_ids`/`cf` stay raw strings here (UUID-or-`none`,
    `key:value`) — parsed by `parse_id_or_none`/`parse_cf` at query-build time
    so malformed values yield a 422 with a clear message.
    """

    project_id: uuid.UUID | None = None
    state_ids: tuple[uuid.UUID, ...] = ()
    categories: tuple[StateCategory, ...] = ()
    kinds: tuple[ItemKind, ...] = ()
    priorities: tuple[Priority, ...] = ()
    parent_id: uuid.UUID | None = None
    assignee_ids: tuple[str, ...] = ()
    team_ids: tuple[str, ...] = ()
    # UUID-or-`none` (backlog = items with no cycle) — the cycle/planning pages'
    # server-side filter, replacing their old fetch-everything-and-filter-client-side.
    cycle_ids: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    cf: tuple[str, ...] = ()
    # Spec 38: archived items are hidden by default; True = archived ONLY.
    archived: bool = False


@dataclass(frozen=True)
class IdOrNoneFilter:
    """A repeatable id filter that may also include the literal `none` (IS NULL)."""

    ids: tuple[uuid.UUID, ...] = ()
    include_none: bool = False

    def __bool__(self) -> bool:
        return bool(self.ids) or self.include_none


@dataclass
class CfFilter:
    """One parsed `cf=key:value` condition, coerced per the field registry.

    `payload` is the JSONB containment document: `{key: value}` for scalar
    equality, `{key: [value]}` for multi_select containment.
    """

    key: str
    payload: dict[str, Any]


def parse_id_or_none(param: ItemFilterParam, values: Sequence[str] | None) -> IdOrNoneFilter:
    """Parse repeatable UUID-or-`none` values (assignee_id / team_id)."""
    ids: list[uuid.UUID] = []
    include_none = False
    for value in values or ():
        if value == NONE_LITERAL:
            include_none = True
            continue
        try:
            ids.append(uuid.UUID(value))
        except ValueError:
            raise FilterParseError(
                f"{param}: expected a UUID or '{NONE_LITERAL}', got '{value}'"
            ) from None
    return IdOrNoneFilter(ids=tuple(ids), include_none=include_none)


def _coerce_cf_value(key: str, raw: str, definition: FieldDefinition) -> dict[str, Any]:
    """Turn the raw query-string value into the JSONB containment payload."""
    field_type = FieldType(definition.type)
    if field_type is FieldType.MULTI_SELECT:
        return {key: [raw]}  # containment: the stored list must include the value
    value: Any = raw
    if field_type is FieldType.NUMBER:
        try:
            value = float(raw) if "." in raw else int(raw)
        except ValueError:
            raise FilterParseError(
                f"{ItemFilterParam.CF} {key}: expected a number, got '{raw}'"
            ) from None
    elif field_type is FieldType.BOOLEAN:
        if raw not in ("true", "false"):
            raise FilterParseError(f"{ItemFilterParam.CF} {key}: expected 'true' or 'false'")
        value = raw == "true"
    elif field_type is FieldType.DURATION:
        try:
            value = int(raw)
        except ValueError:
            raise FilterParseError(
                f"{ItemFilterParam.CF} {key}: expected whole minutes, got '{raw}'"
            ) from None
    return {key: value}


def parse_cf(
    values: Sequence[str] | None, definitions_by_key: Mapping[str, FieldDefinition]
) -> list[CfFilter]:
    """Parse repeatable `cf=key:value` params against the field registry."""
    parsed: list[CfFilter] = []
    for value in values or ():
        key, separator, raw = value.partition(CF_SEPARATOR)
        if not separator or not key:
            raise FilterParseError(
                f"{ItemFilterParam.CF}: expected 'key{CF_SEPARATOR}value', got '{value}'"
            )
        definition = definitions_by_key.get(key)
        if definition is None:
            raise FilterParseError(f"{ItemFilterParam.CF}: unknown custom field '{key}'")
        parsed.append(CfFilter(key=key, payload=_coerce_cf_value(key, raw, definition)))
    return parsed
